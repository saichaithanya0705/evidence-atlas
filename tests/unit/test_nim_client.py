import ssl

from backend.app.core.config import Settings
from backend.app.core.nim_client import create_nim_client


def test_openai_nim_client_uses_an_explicit_certifi_backed_tls_context():
    settings = Settings(
        _env_file=None,
        DEVICE="cpu",
        LLM_MODE="nim",
        NVIDIA_API_KEY="fixture-only-key",
    )
    client = create_nim_client(settings)
    try:
        http_client = client._client
        context = http_client._transport._pool._ssl_context
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
    finally:
        client.close()


def test_planner_judge_synthesis_and_verifier_share_the_safe_nim_transport(monkeypatch):
    from backend.app.conversation import agent as agent_module
    from backend.app.conversation.agent import ConversationAgent
    from backend.app.workflow import judge as judge_module
    from backend.app.workflow import synthesis as synthesis_module
    from backend.app.workflow import verification as verification_module
    from backend.app.workflow.judge import EvidenceSufficiencyJudge
    from backend.app.workflow.synthesis import EvidenceSynthesizer
    from backend.app.workflow.verification import SemanticClaimVerifier

    settings = Settings(
        _env_file=None,
        DEVICE="cpu",
        LLM_MODE="nim",
        NVIDIA_API_KEY="fixture-only-key",
    )
    built = []

    def tracked_factory(config):
        client = create_nim_client(config)
        built.append(client)
        return client

    for module in (agent_module, judge_module, synthesis_module, verification_module):
        monkeypatch.setattr(module, "create_nim_client", tracked_factory)

    assert ConversationAgent(settings).completion_client is not None
    judge = EvidenceSufficiencyJudge(settings=settings)
    synthesizer = EvidenceSynthesizer(settings=settings)
    verifier = SemanticClaimVerifier(settings=settings)
    assert judge._get_client() is not None
    assert synthesizer._get_client() is not None
    assert verifier._get_client() is not None
    assert len(built) == 4
    try:
        assert all(client._client._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED for client in built)
    finally:
        for client in built:
            client.close()
