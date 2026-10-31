"""T217B lost-reply recovery uses read-only evidence and one dispatch."""
import pytest

from ag import state, status
from ag.transport import Result
from test_core import cfg
from test_slurm import multi, submitted


@pytest.mark.parametrize('previous', ['submitted', 'running', 'interrupted', 'unknown'])
def test_bound_slurm_missing_observation_preserves_state(multi, tmp_path, monkeypatch, previous):
    path, manifest, fake = submitted(multi, tmp_path, monkeypatch)
    if previous != 'submitted':
        state.write(path, previous)
    binding = (path / 'submission.json').read_bytes()
    claim = (path / '.submit-claim').read_bytes()
    fake.exact = fake.accounting = Result()

    result = status.check(multi, path, fake)

    assert result['state'] == previous
    assert result['job_id'] == 'batch:123'
    assert result['scheduler_state'] is None
    assert 'not observed' in result['note']
    assert (path / 'submission.json').read_bytes() == binding
    assert (path / '.submit-claim').read_bytes() == claim
    assert not {'submit', 'create_attempt', 'upload'} & set(fake.operations())
