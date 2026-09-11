"""WatchActivities must import generated scheduler stubs without a `zndx` package."""


def test_scheduler_pb2_imports_without_top_level_zndx():
    import gaius.engine.generated.zndx.engine.v1.engine_pb2 as engine_pb2
    import gaius.engine.generated.zndx.scheduler.v1.scheduler_pb2 as scheduler_pb2
    import gaius.engine.generated.zndx.scheduler.v1.scheduler_pb2_grpc as scheduler_grpc

    assert scheduler_pb2.DESCRIPTOR is not None
    assert engine_pb2.DESCRIPTOR is not None
    assert scheduler_grpc.SchedulerStub is not None
