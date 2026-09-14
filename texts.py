"""Every user facing string. English only, no Hinglish."""

CONSENT = (
    "Welcome to the {brand} Score Report Bot for {exam}.\n\n"
    "Here is how it works. You register with your exam details, and once the "
    "answer key is out you submit your marks. The bot then shows where you "
    "stand against every other candidate who has submitted.\n\n"
    "Your marks are pooled anonymously. Your name is never shown publicly.\n"
    "You can remove your data any time with /deletemydata.\n\n"
    "Let's begin."
)

ASK_NAME = "What is your name?"
ASK_ROLL = (
    "Enter your CBT roll number.\n\n"
    "This is used to make sure nobody submits twice. It is never shown publicly."
)
ASK_DATE = "Which date was your exam?"
ASK_SHIFT = "Which shift?"
ASK_CATEGORY = "Your category?"
ASK_CENTRE = (
    "Last optional question. Which centre did you appear at?\n\n"
    "This does not affect your result, it only helps the report."
)

REGISTERED = (
    "Registered.\n\n"
    "Name: {name}\n"
    "Exam: {date}, Shift {shift}\n"
    "Category: {category}\n\n"
    "Score submission opens {unlock}. You will get a message here the "
    "moment it is live."
)

SUBMISSION_LOCKED = (
    "Score submission opens {unlock}.\n\n"
    "You are already registered, so you will be notified here as soon as it "
    "is open. Nothing else to do right now."
)

SUBMISSION_OPEN_BROADCAST = (
    "Score submission is now OPEN.\n\n"
    "Tap Submit My Marks to enter your score and see where you stand."
)

ASK_GK_ATTEMPTED = (
    "General Knowledge section.\n\n"
    "How many questions did you attempt out of 50?"
)
ASK_GK_MARKS = (
    "Your GK marks as per the answer key, after 0.25 negative marking.\n\n"
    "Example: 38.25"
)
ASK_EN_ATTEMPTED = "English section.\n\nHow many questions did you attempt out of 20?"
ASK_EN_MARKS = (
    "Your English marks as per the answer key, after 0.25 negative marking.\n\n"
    "Example: 14.5"
)

CONFIRM_SUMMARY = (
    "Please check before saving.\n\n"
    "Name: {name}\n"
    "Roll No: {roll}\n"
    "Exam: {date}, Shift {shift}\n"
    "Category: {category}\n\n"
    "GK: {gk} out of 50 ({gk_att} attempted)\n"
    "English: {en} out of 20 ({en_att} attempted)\n"
    "Total: {total} out of 70\n\n"
    "Is this correct?"
)

RESULT_CARD = (
    "Your score is saved.\n\n"
    "Total: {total} out of 70\n"
    "GK: {gk}   English: {en}\n\n"
    "Your position in {date} Shift {shift}:\n"
    "Top {percentile}% of {shift_n} candidates who submitted\n\n"
    "Your shift median: {shift_median}\n"
    "{category} category median: {cat_median}\n"
    "{band_line}\n"
    "Based on {total_n} submissions so far. The more people submit, the "
    "sharper this gets."
)

RESULT_DISCLAIMER = (
    "\nNote: SSSC normalises marks across shifts, so your final score will "
    "differ from your raw score. This report shows where you stand among "
    "candidates who submitted, not your official result."
)

SHARE_PROMPT = (
    "\nShare this bot with your batchmates. Every extra submission makes the "
    "cutoff estimate more accurate for everyone, including you."
)

REFERRAL_LOCKED = (
    "The full shift by shift breakdown unlocks when 3 people submit using "
    "your link.\n\n"
    "So far: {count} of 3\n\n"
    "Your link:\n{link}"
)

ALREADY_SUBMITTED = (
    "You have already submitted.\n\n"
    "Total: {total} out of 70\n\n"
    "If the final answer key changed your score, tap Submit My Marks again "
    "to update it. Your earlier score is kept for comparison."
)

# --- errors ---
ERR_NAME = "Please enter your name as text."
ERR_ROLL_TAKEN = (
    "This roll number is already registered from another account. If this is "
    "your roll number and you have lost access to that account, contact support."
)
ERR_NUMBER = "Please send a number only."
ERR_ATTEMPTED_RANGE = "Attempted questions must be between 0 and {max_q}."
ERR_MARKS_STEP = (
    "With 0.25 negative marking, marks are always a multiple of 0.25. "
    "Please check and send again."
)
ERR_MARKS_RANGE = "Marks for this section must be between {lo} and {hi}."
ERR_IMPOSSIBLE = (
    "That score is not possible with {att} questions attempted.\n\n"
    "With 0.25 negative marking the formula is:\n"
    "marks = correct - 0.25 x wrong\n\n"
    "The nearest possible scores are {near}. Please check and send again."
)

NOT_REGISTERED = "Tap Register first so the bot knows your exam date and shift."
NOT_ADMIN = "This command is for administrators only."
CANCELLED = "Cancelled. Back to the main menu."
DELETED = "Your data has been removed. You can register again any time."

# --- stats ---
LIVE_STATS_PRE = (
    "{exam} - Live Registration Count\n\n"
    "Registered: {n}\n\n"
    "Score submission opens {unlock}."
)

NO_DATA_YET = "Not enough submissions yet for this view. Please check back shortly."

# --- answer key ---
KEY_MENU = (
    "Shift wise answer keys.\n\n"
    "Green means received, grey means still missing. Tap any slot to upload "
    "that shift's key.\n\n"
    "Please upload the official shift wise answer key PDF only. Do not upload "
    "your personal response sheet, it carries your roll number and name."
)
KEY_ASK_FILE = "Send the answer key PDF for {date}, Shift {shift}."
KEY_SAVED = "Saved. Thank you, this helps everyone."
KEY_WRONG_TYPE = "Please send a PDF file."
