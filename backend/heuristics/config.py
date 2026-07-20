import re
import statistics

SMALL_STEP_MIN = 90
LOW_PCT = 5
NEGLIGIBLE_PCT = 2
WAIT_TO_PROCESS_RATIO = 3
PARTICIPANT_MAX = 4
DEPT_MAX = 3

AUTOMATION_KW = [
    "calculate", "generate", "check", "send", "notify", "record", "update",
    "compile", "collect", "verify", "validate", "schedule", "print", "file",
    "log", "enter", "upload",
]

EXTERNAL_AUTHORITY_KW = [
    "regulator", "regulatory", "government", "ministry", "commission",
    "court", "bank", "vendor", "auditor", "board", "agency", "authority",
    "council", "committee", "federal", "national", "tribunal",
    "commissioner", "registrar", "license", "licensing", "accreditation",
    "embassy", "consulate", "third party", "external",
]

PASS_FAIL_WORDS = {
    "yes", "no", "approved", "not approved", "pass", "fail",
    "accept", "reject", "accepted", "rejected", "granted", "denied",
}


def keyword_match(text, keywords):
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in keywords)


def internal_job_names(wp):
    names = set()
    for task in wp.tasks.values():
        for jt in task.get("jobTasks") or []:
            job = jt.get("job") or {}
            name = job.get("name")
            if name:
                names.add(name.strip().lower())
    return names


def has_external_authority_reference(task, wp):
    text = f"{task.get('task_name', '')} {task.get('task_overview', '')}"
    if keyword_match(text, EXTERNAL_AUTHORITY_KW):
        return True

    known_names = internal_job_names(wp)

    acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
    for acronym in acronyms:
        if acronym.lower() not in known_names:
            return True

    proper_nouns = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
    for phrase in proper_nouns:
        if phrase.strip().lower() not in known_names:
            return True

    return False


def get_role_entry(task, role):
    for jt in task.get("jobTasks") or []:
        if jt.get("role") == role:
            return jt
    return None


def get_r_job(task):
    entry = get_role_entry(task, "R")
    return entry.get("job") if entry else None


def unique_job_ids(task):
    return {jt.get("job_id") for jt in (task.get("jobTasks") or []) if jt.get("job_id") is not None}


def unique_function_ids(task):
    ids = set()
    for jt in task.get("jobTasks") or []:
        job = jt.get("job") or {}
        fid = job.get("function_id")
        if fid is not None:
            ids.add(fid)
    return ids


def successor_of(wp, node_id):
    succs = wp.outgoing.get(node_id, [])
    return succs[0] if len(succs) == 1 else None


def median_job_level(wp):
    levels = {}
    for task in wp.tasks.values():
        for jt in task.get("jobTasks") or []:
            job = jt.get("job") or {}
            job_id = jt.get("job_id")
            level = job.get("job_level_id")
            if job_id is not None and level is not None:
                levels[job_id] = level
    values = list(levels.values())
    return statistics.median(values) if values else None


def is_pass_fail_gateway(wp, gateway_node):
    if gateway_node not in wp.gateways:
        return False
    gw = wp.gateways[gateway_node]
    if gw.gateway_type != "EXCLUSIVE":
        return False
    targets = wp.outgoing.get(gateway_node, [])
    if len(targets) != 2:
        return False
    conditions = [(gw.branch_conditions.get(t) or "").strip().lower() for t in targets]
    if not all(conditions):
        return False
    return all(c in PASS_FAIL_WORDS for c in conditions)