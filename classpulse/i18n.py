"""Server-side texts that end up in files and offline AI output (English and Hebrew).

Screen texts live in static/common.js. Error messages are translated in the
browser by their stable error code.
"""
from __future__ import annotations

LABELS = {
    "en": {
        "num": "#", "student_id": "Student ID", "name": "Name", "time": "Check-in time",
        "status": "Status", "method": "Method", "location": "Location", "session": "Session", "date": "Date",
        "on_time": "On time", "late": "Late", "qr": "QR", "code": "Typed code", "manual": "Added by lecturer",
        "geo_ok": "In class", "geo_far": "Far ({m} m)", "geo_none": "No location", "geo_": "",
        "attendance": "Attendance", "polls": "Polls", "comments": "Comments",
        "question": "Question", "option": "Option", "votes": "Votes", "percent": "%",
        "author": "Author", "comment": "Comment", "upvotes": "Upvotes", "answered": "Answered",
        "yes": "Yes", "no": "No", "Anonymous": "Anonymous",
        "summary_sheet": "Attendance summary", "present": "Present", "percent_present": "% present",
        "sum_topics": "Key topics", "sum_points": "Main points",
        "rev_short": "Your answer is short ({words} words, class average {avg}). Consider expanding the explanation.",
        "rev_long": "Your answer is long ({words} words, class average {avg}). Check that every paragraph is needed.",
        "rev_ok": "The length is in line with the class ({words} words).",
        "rev_missing": "Most classmates discussed: {terms}. Check whether these belong in your answer.",
        "rev_unique": "Ideas only you raised: {terms}.",
        "rev_overlap": "Warning: {pct}% overlap with another submission.",
        "rev_alone": "You are the first to submit, so there is no class comparison yet.",
        "rev_offline": "(Offline review. With an API key, the review is written by the LLM.)",
    },
    "he": {
        "num": "#", "student_id": "ת.ז.", "name": "שם", "time": "שעת כניסה",
        "status": "סטטוס", "method": "אופן הרישום", "location": "מיקום", "session": "שיעור", "date": "תאריך",
        "on_time": "בזמן", "late": "איחור", "qr": "סריקת QR", "code": "הקלדת קוד", "manual": "נוסף על ידי המרצה",
        "geo_ok": "בכיתה", "geo_far": "רחוק ({m} מ׳)", "geo_none": "בלי מיקום", "geo_": "",
        "attendance": "נוכחות", "polls": "סקרים", "comments": "שאלות והערות",
        "question": "שאלה", "option": "אפשרות", "votes": "קולות", "percent": "%",
        "author": "כותב", "comment": "הערה", "upvotes": "הצבעות בעד", "answered": "נענתה",
        "yes": "כן", "no": "לא", "Anonymous": "אנונימי",
        "summary_sheet": "סיכום נוכחות", "present": "נוכחויות", "percent_present": "% נוכחות",
        "sum_topics": "נושאים מרכזיים", "sum_points": "נקודות עיקריות",
        "rev_short": "התשובה שלך קצרה ({words} מילים, הממוצע בכיתה {avg}). כדאי להרחיב את ההסבר.",
        "rev_long": "התשובה שלך ארוכה ({words} מילים, הממוצע בכיתה {avg}). כדאי לבדוק שכל פסקה נחוצה.",
        "rev_ok": "אורך התשובה דומה לשאר הכיתה ({words} מילים).",
        "rev_missing": "רוב הכיתה התייחסה ל: {terms}. כדאי לבדוק אם זה חסר בתשובה שלך.",
        "rev_unique": "רעיונות שרק את/ה העלית: {terms}.",
        "rev_overlap": "שימו לב: חפיפה של {pct}% עם הגשה אחרת.",
        "rev_alone": "זו ההגשה הראשונה, ולכן עדיין אין השוואה לכיתה.",
        "rev_offline": "(ביקורת במצב לא מקוון. עם מפתח API הביקורת נכתבת על ידי מודל שפה.)",
    },
}


def tr(lang: str, key: str, **kw) -> str:
    table = LABELS.get(lang, LABELS["en"])
    return table.get(key, LABELS["en"].get(key, key)).format(**kw)
