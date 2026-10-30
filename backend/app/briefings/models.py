"""What a briefing contains, before any wording by a model.

Every text field is written by code and cites quantities only as fact references (`{{F<id>}}`)
and entities only as entity references (`{{E:...}}`): code text holds no number of its own, which
a test checks with the verifier. Rendering for a channel (app.channels.messages) replaces the
references with formatted facts and escaped names.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BriefingKind(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ButtonKind(StrEnum):
    APPROVE = "approve"  # a signed approval link for the recommended option
    REVIEW = "review"  # the decision's options on the web platform
    EVIDENCE = "evidence"  # the incident (its facts and investigation)


class Button(_Frozen):
    kind: ButtonKind
    label: str
    decision_id: str | None = None
    option_id: str | None = None
    incident_id: str | None = None


class Item(_Frozen):
    text: str
    level: str | None = None  # an incident's alert level, when the item is an incident
    incident_id: str | None = None
    decision_id: str | None = None
    buttons: tuple[Button, ...] = ()


class Table(_Frozen):
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]  # cells: entity or fact references, or code words


class Section(_Frozen):
    key: str
    title: str
    items: tuple[Item, ...] = ()
    table: Table | None = None
    empty: str | None = None  # shown when the section has nothing


class Document(_Frozen):
    """A message's content: a headline and sections, citing facts and entities by reference
    (a briefing, an alert or a decision)."""

    headline: str
    sections: tuple[Section, ...]
    fact_ids: tuple[int, ...] = Field(default=())  # every fact the text cites
    entities: tuple[str, ...] = ()  # every entity the text cites

    def texts(self) -> list[str]:
        out = [self.headline]
        for section in self.sections:
            out.append(section.title)
            out.extend(i.text for i in section.items)
            if section.empty:
                out.append(section.empty)
            if section.table is not None:
                out.extend(section.table.columns)
                out.extend(cell for row in section.table.rows for cell in row)
        return out


class BriefingContent(Document):
    kind: BriefingKind
    period_start: date  # data days covered: [period_start, period_end)
    period_end: date
    nothing_material: bool = False
    incident_ids: tuple[str, ...] = ()  # incidents it shows (top items, data notice)
