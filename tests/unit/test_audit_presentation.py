import pytest
from fastapi import HTTPException
from backend.app.admin.routes import _date_bound
from backend.app.storage.audits import _admin_projection, _safe_trace


def test_nested_timings_are_bounded_validated_and_safe():
    result = _safe_trace({'timings_ms': {'total': 10, 'prompt': 'secret', 'stages': [
        {'stage': 'synthesize', 'duration_ms': 8, 'iteration': 0, 'prompt': 'secret'},
        {'stage': 'retrieve', 'duration_ms': float('nan')},
        {'stage': 'secret', 'duration_ms': 1},
    ]}, 'synthesis_metadata': {'mode': 'nvidia_nim', 'timings_ms': {'generation': 7, 'prompt': 'secret'}}})
    assert result['timings_ms'] == {'total': 10, 'stages': [{'stage': 'synthesize', 'duration_ms': 8, 'iteration': 0}]}
    assert result['synthesis_metadata']['timings_ms'] == {'generation': 7}
    assert 'secret' not in str(result)


def test_projection_preserves_times_and_sums_repeated_stages():
    events = [{'stage': 'retrieve', 'timestamp': '2026-10-01T00:00:01+00:00', 'payload': {'status':'completed','duration_ms':4}},
              {'stage': 'retrieve', 'timestamp': '2026-10-01T00:00:02+00:00', 'payload': {'status':'completed','duration_ms':6}}]
    result = _admin_projection({'id':'run'}, events, None, {'execution_mode':'prior_evidence','query_plan':{'route':'MODERATE'}})
    assert result['stage_durations_ms'] == {'retrieve':10}
    assert result['events'][0]['timestamp'] == events[0]['timestamp']
    assert result['trace_availability'] == 'recorded'
    assert result['final_route'] == 'MODERATE'
    assert _admin_projection({}, [], None, None)['trace_availability'] == 'not_recorded'


def test_date_bounds_normalize_offsets_and_reject_invalid_input():
    assert _date_bound('2026-10-01T00:00:00+05:30') == '2026-09-30T18:30:00+00:00'
    assert _date_bound('2026-10-01') == '2026-10-01T00:00:00+00:00'
    for value in ['not-a-date','2026-99-99','2026-10-01T00:00:00']:
        with pytest.raises(HTTPException):
            _date_bound(value)
