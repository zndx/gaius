"""Thermal emergency monitor for GPU hardware protection.

SEV-0 critical safety system that monitors GPU thermal state and fan speeds,
providing automatic emergency shutdown when critical thresholds are exceeded.

This module runs independently of the main health system to ensure
fail-safe operation even when the primary health framework is compromised.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GPUStatus:
    """Current status of a single GPU."""
    index: int
    temperature_c: float = 0.0
    fan_speed_pct: int = 0
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    power_draw_w: float = 0.0
    utilization_pct: int = 0
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class ThermalState:
    """Overall thermal state across all GPUs."""
    gpus: dict[int, GPUStatus] = field(default_factory=dict)
    critical_gpus: list[int] = field(default_factory=list)
    warning_gpus: list[int] = field(default_factory=list)
    fan_failed_gpus: list[int] = field(default_factory=list)
    zero_fan_duration: dict[int, timedelta] = field(default_factory=dict)
    temperature_rise_rates: dict[int, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)


class ThermalEmergencyMonitor:
    """Independent SEV-0 thermal emergency monitor with automatic shutdown."""

    CRITICAL_THRESHOLDS = {
        'fan_speed_zero_duration': 30,
        'temperature_absolute': 80,
        'temperature_warning': 75,
        'temperature_rise_rate': 5,
        'temperature_emergency': 85,
        'fan_speed_warning': 10,
    }

    MONITOR_INTERVAL = 10
    EMERGENCY_LOG = Path("/var/log/gaius_thermal_emergency.log")
    SHUTDOWN_LOG = Path("/var/log/gaius_emergency_shutdown.log")
    STATE_FILE = Path("/var/run/gaius_thermal_monitor.pid")

    def __init__(self):
        self._running = False
        self._shutdown_requested = False
        self._last_state = None
        self._zero_fan_timers = {}
        self._temperature_history = {}
        self._history_window = timedelta(minutes=2)
        self._emergency_triggered = False
        self._ensure_directories()
        self._setup_signals()

    def _ensure_directories(self):
        for log_path in [self.EMERGENCY_LOG, self.SHUTDOWN_LOG]:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def _setup_signals(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        self._shutdown_requested = True
        self._running = False

    async def _get_gpu_status(self) -> dict[int, GPUStatus]:
        gpus = {}
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,temperature.gpu,fan.speed,memory.used,memory.total,power.draw,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 7:
                        try:
                            gpu = GPUStatus(
                                index=int(parts[0]),
                                temperature_c=float(parts[1]),
                                fan_speed_pct=int(parts[2]),
                                memory_used_mb=int(parts[3]),
                                memory_total_mb=int(parts[4]),
                                power_draw_w=float(parts[5]),
                                utilization_pct=int(parts[6]),
                                last_updated=datetime.now()
                            )
                            gpus[gpu.index] = gpu
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass
        return gpus

    def _calculate_rise_rates(self, current_gpus: dict[int, GPUStatus]) -> dict[int, float]:
        rise_rates = {}
        for gpu_idx, gpu in current_gpus.items():
            if gpu_idx not in self._temperature_history:
                self._temperature_history[gpu_idx] = []
            self._temperature_history[gpu_idx].append((gpu.last_updated, gpu.temperature_c))
            cutoff = datetime.now() - self._history_window
            self._temperature_history[gpu_idx] = [(ts, temp) for ts, temp in self._temperature_history[gpu_idx] if ts >= cutoff]
            readings = self._temperature_history[gpu_idx]
            if len(readings) >= 2:
                first_ts, first_temp = readings[0]
                last_ts, last_temp = readings[-1]
                time_diff_minutes = (last_ts - first_ts).total_seconds() / 60.0
                if time_diff_minutes > 0:
                    rise_rates[gpu_idx] = (last_temp - first_temp) / time_diff_minutes
                else:
                    rise_rates[gpu_idx] = 0.0
            else:
                rise_rates[gpu_idx] = 0.0
        return rise_rates

    def _update_fan_timers(self, current_gpus: dict[int, GPUStatus]) -> dict[int, timedelta]:
        zero_fan_durations = {}
        current_time = datetime.now()
        for gpu_idx, gpu in current_gpus.items():
            if gpu.fan_speed_pct == 0:
                if gpu_idx not in self._zero_fan_timers:
                    self._zero_fan_timers[gpu_idx] = current_time
                else:
                    zero_fan_durations[gpu_idx] = current_time - self._zero_fan_timers[gpu_idx]
            else:
                if gpu_idx in self._zero_fan_timers:
                    del self._zero_fan_timers[gpu_idx]
        return zero_fan_durations

    async def _check_gpu_thermal(self, gpu: GPUStatus, zero_fan_duration: Optional[timedelta] = None, rise_rate: float = 0.0):
        is_critical = False
        is_warning = False
        is_emergency = False
        if zero_fan_duration and zero_fan_duration.total_seconds() >= self.CRITICAL_THRESHOLDS['fan_speed_zero_duration']:
            is_emergency = True
            is_critical = True
        elif gpu.fan_speed_pct == 0:
            is_critical = True
        elif gpu.fan_speed_pct <= self.CRITICAL_THRESHOLDS['fan_speed_warning']:
            is_warning = True
        if gpu.temperature_c >= self.CRITICAL_THRESHOLDS['temperature_emergency']:
            is_emergency = True
        elif gpu.temperature_c >= self.CRITICAL_THRESHOLDS['temperature_absolute']:
            is_critical = True
        elif gpu.temperature_c >= self.CRITICAL_THRESHOLDS['temperature_warning']:
            is_warning = True
        if rise_rate >= self.CRITICAL_THRESHOLDS['temperature_rise_rate']:
            if gpu.temperature_c >= 70:
                is_emergency = True
            else:
                is_critical = True
        return is_critical, is_warning, is_emergency

    async def _emergency_shutdown(self, reason: str) -> bool:
        self._emergency_triggered = True
        with open(self.SHUTDOWN_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] EMERGENCY SHUTDOWN: {reason}\n")
        logger.error(f"EMERGENCY SHUTDOWN: {reason}")
        try:
            with open("/proc/sysrq-trigger", "w") as f:
                f.write("b")
            return True
        except (IOError, PermissionError):
            pass
        try:
            subprocess.run(["shutdown", "-h", "now", f"GPU thermal emergency: {reason}"], timeout=5)
            return True
        except Exception:
            pass
        return False

    async def _check_and_respond(self) -> ThermalState:
        gpus = await self._get_gpu_status()
        if not gpus:
            return ThermalState()
        zero_fan_durations = self._update_fan_timers(gpus)
        rise_rates = self._calculate_rise_rates(gpus)
        state = ThermalState(
            gpus=gpus,
            zero_fan_duration=zero_fan_durations,
            temperature_rise_rates=rise_rates,
            last_updated=datetime.now()
        )
        for gpu_idx, gpu in gpus.items():
            zero_duration = zero_fan_durations.get(gpu_idx)
            rise_rate = rise_rates.get(gpu_idx, 0.0)
            is_critical, is_warning, is_emergency = await self._check_gpu_thermal(gpu, zero_duration, rise_rate)
            if is_emergency:
                state.critical_gpus.append(gpu_idx)
                state.fan_failed_gpus.append(gpu_idx)
                reason = f"GPU {gpu_idx}: {gpu.temperature_c}°C, fan={gpu.fan_speed_pct}%, rise={rise_rate:.1f}°C/min"
                await self._emergency_shutdown(reason)
            elif is_critical:
                state.critical_gpus.append(gpu_idx)
                if gpu.fan_speed_pct == 0:
                    state.fan_failed_gpus.append(gpu_idx)
                logger.warning(f"CRITICAL: GPU {gpu_idx} at {gpu.temperature_c}°C, fan={gpu.fan_speed_pct}%")
            elif is_warning:
                state.warning_gpus.append(gpu_idx)
                logger.warning(f"WARNING: GPU {gpu_idx} at {gpu.temperature_c}°C, fan={gpu.fan_speed_pct}%")
        self._last_state = state
        return state

    async def monitor(self):
        self._running = True
        try:
            with open(self.STATE_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        try:
            while self._running and not self._emergency_triggered:
                await self._check_and_respond()
                await asyncio.sleep(self.MONITOR_INTERVAL)
        finally:
            self._running = False
            try:
                self.STATE_FILE.unlink(missing_ok=True)
            except Exception:
                pass

    def start(self):
        if self._running:
            return
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.monitor())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()

    def stop(self):
        self._running = False
        self._shutdown_requested = True
