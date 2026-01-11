import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from assistant.google.auth import google_auth

logger = logging.getLogger(__name__)

FOLDER_STRUCTURE = {
    "Second Brain": {
        "Research": {"General": {}},
        "Meeting Notes": {},
        "Reports": {},
        "Drafts": {},
    }
}


class DocType(Enum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    web_view_link: str
    parent_id: str | None = None
    
    @property
    def is_folder(self) -> bool:
        return self.mime_type == "application/vnd.google-apps.folder"
    
    @property
    def doc_type(self) -> DocType | None:
        mime_map = {
            "application/vnd.google-apps.document": DocType.DOCUMENT,
            "application/vnd.google-apps.spreadsheet": DocType.SPREADSHEET,
            "application/vnd.google-apps.presentation": DocType.PRESENTATION,
        }
        return mime_map.get(self.mime_type)


class DriveClient:
    def __init__(self):
        self._drive_service = None
        self._docs_service = None
        self._sheets_service = None
        self._folder_cache: dict[str, str] = {}
    
    def _get_drive_service(self):
        if not google_auth.is_authenticated():
            if not google_auth.load_saved_credentials():
                raise RuntimeError("Google Drive not authenticated. Run /setup_google first.")
        
        if not self._drive_service:
            self._drive_service = build("drive", "v3", credentials=google_auth.credentials)
        return self._drive_service
    
    def _get_docs_service(self):
        if not google_auth.is_authenticated():
            if not google_auth.load_saved_credentials():
                raise RuntimeError("Google Docs not authenticated. Run /setup_google first.")
        
        if not self._docs_service:
            self._docs_service = build("docs", "v1", credentials=google_auth.credentials)
        return self._docs_service
    
    def _get_sheets_service(self):
        if not google_auth.is_authenticated():
            if not google_auth.load_saved_credentials():
                raise RuntimeError("Google Sheets not authenticated. Run /setup_google first.")
        
        if not self._sheets_service:
            self._sheets_service = build("sheets", "v4", credentials=google_auth.credentials)
        return self._sheets_service
    
    async def ensure_folder_structure(self) -> str:
        return await self._ensure_folder_recursive("Second Brain", FOLDER_STRUCTURE["Second Brain"])
    
    async def _ensure_folder_recursive(
        self,
        folder_name: str,
        children: dict[str, Any],
        parent_id: str | None = None,
    ) -> str:
        cache_key = f"{parent_id or 'root'}:{folder_name}"
        if cache_key in self._folder_cache:
            folder_id = self._folder_cache[cache_key]
        else:
            folder_id = await self._find_or_create_folder(folder_name, parent_id)
            self._folder_cache[cache_key] = folder_id
        
        for child_name, child_children in children.items():
            await self._ensure_folder_recursive(child_name, child_children, folder_id)
        
        return folder_id
    
    async def _find_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        service = self._get_drive_service()
        
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        try:
            results = service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get("files", [])
            
            if files:
                return files[0]["id"]
            
            file_metadata: dict[str, Any] = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if parent_id:
                file_metadata["parents"] = [parent_id]
            
            folder = service.files().create(body=file_metadata, fields="id").execute()
            logger.info(f"Created folder: {name}")
            return folder["id"]
        except HttpError as e:
            logger.error(f"Failed to find/create folder '{name}': {e}")
            raise
    
    async def get_folder_id(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        current_parent: str | None = None
        
        for part in parts:
            cache_key = f"{current_parent or 'root'}:{part}"
            if cache_key in self._folder_cache:
                current_parent = self._folder_cache[cache_key]
            else:
                folder_id = await self._find_folder(part, current_parent)
                if not folder_id:
                    return None
                self._folder_cache[cache_key] = folder_id
                current_parent = folder_id
        
        return current_parent
    
    async def _find_folder(self, name: str, parent_id: str | None = None) -> str | None:
        service = self._get_drive_service()
        
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        try:
            results = service.files().list(q=query, fields="files(id)").execute()
            files = results.get("files", [])
            return files[0]["id"] if files else None
        except HttpError:
            return None
    
    async def create_document(
        self,
        title: str,
        folder_path: str = "Second Brain/Research/General",
        initial_content: str | None = None,
    ) -> DriveFile:
        service = self._get_drive_service()
        docs_service = self._get_docs_service()
        
        await self.ensure_folder_structure()
        folder_id = await self.get_folder_id(folder_path)
        if not folder_id:
            raise RuntimeError(f"Folder not found: {folder_path}")
        
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id],
        }
        
        try:
            file = service.files().create(body=file_metadata, fields="id,name,mimeType,webViewLink").execute()
            
            if initial_content:
                docs_service.documents().batchUpdate(
                    documentId=file["id"],
                    body={
                        "requests": [
                            {"insertText": {"location": {"index": 1}, "text": initial_content}}
                        ]
                    },
                ).execute()
            
            logger.info(f"Created document: {title}")
            return DriveFile(
                id=file["id"],
                name=file["name"],
                mime_type=file["mimeType"],
                web_view_link=file["webViewLink"],
                parent_id=folder_id,
            )
        except HttpError as e:
            logger.error(f"Failed to create document '{title}': {e}")
            raise
    
    async def create_spreadsheet(
        self,
        title: str,
        folder_path: str = "Second Brain/Research/General",
        headers: list[str] | None = None,
        data: list[list[Any]] | None = None,
    ) -> DriveFile:
        service = self._get_drive_service()
        sheets_service = self._get_sheets_service()
        
        await self.ensure_folder_structure()
        folder_id = await self.get_folder_id(folder_path)
        if not folder_id:
            raise RuntimeError(f"Folder not found: {folder_path}")
        
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [folder_id],
        }
        
        try:
            file = service.files().create(body=file_metadata, fields="id,name,mimeType,webViewLink").execute()
            
            if headers or data:
                values = []
                if headers:
                    values.append(headers)
                if data:
                    values.extend(data)
                
                if values:
                    sheets_service.spreadsheets().values().update(
                        spreadsheetId=file["id"],
                        range="A1",
                        valueInputOption="RAW",
                        body={"values": values},
                    ).execute()
            
            logger.info(f"Created spreadsheet: {title}")
            return DriveFile(
                id=file["id"],
                name=file["name"],
                mime_type=file["mimeType"],
                web_view_link=file["webViewLink"],
                parent_id=folder_id,
            )
        except HttpError as e:
            logger.error(f"Failed to create spreadsheet '{title}': {e}")
            raise
    
    async def create_meeting_notes(
        self,
        meeting_title: str,
        attendees: list[str] | None = None,
        agenda: list[str] | None = None,
    ) -> DriveFile:
        today = datetime.now().strftime("%Y-%m-%d")
        title = f"{today} - {meeting_title}"
        
        content_parts = [f"# {meeting_title}\n\n"]
        content_parts.append(f"**Date:** {today}\n\n")
        
        if attendees:
            content_parts.append("**Attendees:**\n")
            for attendee in attendees:
                content_parts.append(f"- {attendee}\n")
            content_parts.append("\n")
        
        if agenda:
            content_parts.append("**Agenda:**\n")
            for item in agenda:
                content_parts.append(f"- {item}\n")
            content_parts.append("\n")
        
        content_parts.append("---\n\n## Notes\n\n\n\n## Action Items\n\n- [ ] \n")
        
        return await self.create_document(
            title=title,
            folder_path="Second Brain/Meeting Notes",
            initial_content="".join(content_parts),
        )
    
    async def create_research_document(
        self,
        topic: str,
        project: str | None = None,
        initial_findings: str | None = None,
    ) -> DriveFile:
        title = f"Research Notes - {topic}"
        folder_path = f"Second Brain/Research/{project}" if project else "Second Brain/Research/General"
        
        if project:
            await self._ensure_folder_recursive(
                project,
                {},
                await self.get_folder_id("Second Brain/Research"),
            )
        
        content_parts = [f"# Research: {topic}\n\n"]
        content_parts.append(f"**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        
        if initial_findings:
            content_parts.append("## Findings\n\n")
            content_parts.append(initial_findings)
            content_parts.append("\n\n")
        
        content_parts.append("## Sources\n\n- \n\n## Summary\n\n\n\n## Next Steps\n\n- [ ] \n")
        
        return await self.create_document(
            title=title,
            folder_path=folder_path,
            initial_content="".join(content_parts),
        )
    
    async def create_comparison_sheet(
        self,
        title: str,
        options: list[str],
        criteria: list[str] | None = None,
    ) -> DriveFile:
        headers = ["Criteria"] + options + ["Notes"]
        
        default_criteria = criteria or [
            "Price",
            "Features", 
            "Ease of Use",
            "Support",
            "Integration",
        ]
        
        data = [[criterion] + [""] * (len(options) + 1) for criterion in default_criteria]
        
        return await self.create_spreadsheet(
            title=f"Comparison - {title}",
            folder_path="Second Brain/Research/General",
            headers=headers,
            data=data,
        )
    
    async def append_to_document(self, doc_id: str, content: str) -> None:
        docs_service = self._get_docs_service()
        
        try:
            doc = docs_service.documents().get(documentId=doc_id).execute()
            end_index = doc["body"]["content"][-1]["endIndex"] - 1
            
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {"insertText": {"location": {"index": end_index}, "text": content}}
                    ]
                },
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to append to document: {e}")
            raise
