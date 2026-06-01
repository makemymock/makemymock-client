from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class TargetExam(str, Enum):
    JEE_MAIN = "jee_main"
    JEE_ADVANCED = "jee_advanced"
    BOARDS = "boards"
    OTHER = "other"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class ClassGrade(str, Enum):
    """Common Indian school grade tags relevant to the target exams above."""
    CLASS_9 = "9"
    CLASS_10 = "10"
    CLASS_11 = "11"
    CLASS_12 = "12"
    DROPPER = "dropper"


NonEmptyStr = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
PhoneStr = Annotated[
    str,
    StringConstraints(min_length=7, max_length=20, pattern=r"^\+?[0-9 \-]+$"),
]


class ProfileCreateRequest(BaseModel):
    full_name: NonEmptyStr
    date_of_birth: date
    class_grade: ClassGrade
    target_exam: TargetExam
    state: NonEmptyStr
    school_name: NonEmptyStr
    city: NonEmptyStr
    preferred_language: NonEmptyStr
    phone_number: PhoneStr
    gender: Gender


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[NonEmptyStr] = None
    date_of_birth: Optional[date] = None
    class_grade: Optional[ClassGrade] = None
    target_exam: Optional[TargetExam] = None
    state: Optional[NonEmptyStr] = None
    school_name: Optional[NonEmptyStr] = None
    city: Optional[NonEmptyStr] = None
    preferred_language: Optional[NonEmptyStr] = None
    phone_number: Optional[PhoneStr] = None
    gender: Optional[Gender] = None


class ProfileResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    user_id: str
    full_name: str
    date_of_birth: date
    class_grade: ClassGrade
    target_exam: TargetExam
    state: str
    school_name: str
    city: str
    preferred_language: str
    phone_number: str
    gender: Gender
    tours_completed: list[str] = []
    created_at: datetime
    updated_at: datetime = Field(...)
