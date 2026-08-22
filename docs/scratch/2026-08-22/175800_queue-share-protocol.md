# Queue share requests (WRK occupancy over time)

`zndx.scheduler.v1.Scheduler/RequestQueueShare` records peer occupancy
intent so Signals can see guarantee floors as Gaius WRK mix changes.
YK preemption needs the queue under guarantee. Apply/YK interop is
Signals later; UNIMPLEMENTED is honest until then.
