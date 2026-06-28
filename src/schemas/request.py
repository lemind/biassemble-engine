from pydantic import BaseModel


class StoryAnalysis(BaseModel):
    themes: list[str] = []
    beliefs: list[str] = []
    claims: list[str] = []


class RetrieveRequest(BaseModel):
    story: str
    request_id: str | None = None
    story_analysis: StoryAnalysis | None = None
