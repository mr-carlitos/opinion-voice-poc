import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def folder_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".sharepoint.com")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Bitte eine direkte HTTPS-SharePoint-Ordneradresse ohne Abfrage verwenden.")
    path = unquote(parsed.path).rstrip("/")
    if not path.startswith(("/sites/", "/teams/")) or len(path.split("/")) < 5:
        raise ValueError("Die Adresse muss auf einen Ordner in einer Dokumentbibliothek zeigen.")
    if any(part in (".", "..") for part in path.split("/")):
        raise ValueError("Ungueltiger Ordnerpfad.")
    return parsed.hostname.lower(), path


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    graph_client_id: str
    input_url: str
    output_url: str
    project_endpoint: str
    agent_name: str
    model: str
    voice_endpoint: str
    voice_name: str
    voice_api_version: str

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            tenant_id=os.getenv("AZURE_TENANT_ID", ""),
            graph_client_id=os.getenv("GRAPH_CLIENT_ID", ""),
            input_url=os.getenv("SHAREPOINT_INPUT_FOLDER_URL", ""),
            output_url=os.getenv("SHAREPOINT_OUTPUT_FOLDER_URL", ""),
            project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").rstrip("/"),
            agent_name=os.getenv("FOUNDRY_AGENT_NAME", "opinion-voice"),
            model=os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini"),
            voice_endpoint=os.getenv("VOICELIVE_ENDPOINT", "").rstrip("/"),
            voice_name=os.getenv("VOICE_NAME", "de-DE-KatjaNeural"),
            voice_api_version=os.getenv("VOICELIVE_API_VERSION", "2026-04-10"),
        )

    def issues(self) -> list[str]:
        required = {
            "AZURE_TENANT_ID": self.tenant_id,
            "GRAPH_CLIENT_ID": self.graph_client_id,
            "SHAREPOINT_INPUT_FOLDER_URL": self.input_url,
            "SHAREPOINT_OUTPUT_FOLDER_URL": self.output_url,
            "FOUNDRY_PROJECT_ENDPOINT": self.project_endpoint,
            "VOICELIVE_ENDPOINT": self.voice_endpoint,
        }
        issues = [f"{name} fehlt" for name, value in required.items() if not value]
        if self.input_url and self.output_url:
            try:
                input_host, input_path = folder_url(self.input_url)
                output_host, output_path = folder_url(self.output_url)
                input_path, output_path = input_path.casefold(), output_path.casefold()
                if input_host == output_host and (
                    input_path == output_path
                    or output_path.startswith(input_path + "/")
                    or input_path.startswith(output_path + "/")
                ):
                    issues.append("Eingabe- und Ausgabeordner muessen getrennt sein.")
            except ValueError as error:
                issues.append(str(error))
        for endpoint in (self.project_endpoint, self.voice_endpoint):
            if endpoint:
                parsed = urlsplit(endpoint)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or not parsed.hostname.endswith((".ai.azure.com", ".cognitiveservices.azure.com"))
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    issues.append("Foundry und Voice Live benoetigen gueltige Azure-HTTPS-Endpunkte.")
        return issues