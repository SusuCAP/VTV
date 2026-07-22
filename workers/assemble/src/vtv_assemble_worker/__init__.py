from .worker import AssembleWorker


def execute(job):
    return AssembleWorker().execute(job)


__all__ = ["AssembleWorker", "execute"]
