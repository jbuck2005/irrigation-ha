# Tests

The tests run Home Assistant's own test harness against a fake `irrigationd`
(`fake_irrigationd.py`). They never open a TCP connection to a real controller
and never open a valve, so they're safe to run anywhere. The only real sockets
are a few in `test_status.py` and `test_tls.py`, which talk to a throwaway
server over a local socket pair.

They also run on GitHub for every pull request and push to `main`, in the **Tests** workflow.

## Run them

You need Python 3.13 or later. Home Assistant's test harness doesn't support
Windows, so on Windows run these in WSL.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

With [uv](https://docs.astral.sh/uv/), which installs much faster:

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest
```

## Randomized run-queue tests

`test_runqueue_random.py` fires random starts, Stops, Skips and Stop alls at
the run queue, with the fake irrigationd answering after random delays, and
checks rules that must hold whatever the timing: never two zones open at once,
a zone whose last action was Stop ends closed, and Stop all closes everything.
Each seed is one random sequence. Pull requests run 40 seeds; for more:

```bash
IRRIGATION_RANDOM_RUNS=400 pytest tests/test_runqueue_random.py
```

A failure prints its seed, the actions and the commands irrigationd received.
Turn a failure into a plain test in `test_runqueue.py` with fixed timing, so it
stays covered whatever the random seeds do.

## Writing tests

- Use the `loaded` fixture for a controller with four zones already set up,
  and `daemon` to see the commands sent (`daemon.commands`), start a zone as if
  someone else had (`daemon.run(zone, seconds)`), or make replies fail
  (`daemon.fail_with`).
- Use documentation addresses such as `192.0.2.10` and the token `test-token`.
  Never put a real address, host name or token in a test.
