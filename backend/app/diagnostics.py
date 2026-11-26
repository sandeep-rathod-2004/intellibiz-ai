import asyncio
import json

from app.core.config import openai_configuration_metadata, settings
from app.services.copilot import (
    CopilotConfigurationError,
    CopilotProviderError,
    close_provider_clients,
    diagnose_openai_authentication,
)


async def _run_diagnostic() -> tuple[dict[str, object], int]:
    try:
        result = await diagnose_openai_authentication()
        return {
            **result,
            "configuration": openai_configuration_metadata(),
        }, 0
    except CopilotConfigurationError as error:
        return {
            "status": "configuration_required",
            "message": str(error),
            "configuration": openai_configuration_metadata(),
        }, 1
    except CopilotProviderError as error:
        return {
            "status": error.provider_status,
            "message": str(error),
            "upstream_status_code": error.upstream_status_code,
            "provider_error_code": error.provider_error_code,
            "configuration": openai_configuration_metadata(),
        }, 1
    finally:
        await close_provider_clients()


def main() -> int:
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        print(json.dumps({
            "status": "refused",
            "message": "The OpenAI diagnostic command is restricted to local development.",
        }))
        return 2

    result, exit_code = asyncio.run(_run_diagnostic())
    print(json.dumps(result, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
