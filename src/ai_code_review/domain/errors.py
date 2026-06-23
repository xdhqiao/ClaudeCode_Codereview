class NonRetryableReviewError(RuntimeError):
    """A task error that will not improve by retrying the same inputs."""
