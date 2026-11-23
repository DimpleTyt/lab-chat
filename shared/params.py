"""Single source of truth for the variant (assignment) model.

Both the compiler, the validator and the backend import from here,
so defaults never drift between components.
"""
import copy
import re

# Base values: the methodology itself. A user assignment overrides any of them.
DEFAULTS = {
    "domain": "au-team.irpo",
    "workgroup": "au-team",
    "admin_password": "P@ssw0rd",
    "hosts": {
        "hq-srv": "192.168.0.1",
        "hq-cli": "192.168.0.65",
        "hq-rtr": "192.168.0.62",
        "br-srv": "192.168.1.30",
        "isp": "172.16.1.14",
    },
    "storage": {
        "raid_level": 0,
        "disk_pool": ["/dev/sdb", "/dev/sdc", "/dev/sdd", "/dev/sde", "/dev/sdf"],
    },
    "nfs": {"clients": "192.168.0.64/28"},
    "ntp": {"stratum": 5, "allow": ["172.16.4.0/28", "172.16.5.0/28"]},
    "docker": {"port": 8080},
    "web": {"db": "webdb", "user": "webc", "password": "P@ssw0rd"},
    "modules": [1, 2, 3, 4, 5, 6, 7, 9],
}

# Minimal disk count per RAID level.
RAID_MIN = {0: 2, 1: 2, 5: 3, 6: 4, 10: 4}

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        elif value is not None:
            out[key] = copy.deepcopy(value)
    return out


def normalize(variant):
    """Merge an assignment over the defaults and compute derived fields."""
    v = deep_merge(DEFAULTS, variant)

    st = v["storage"]
    st["raid_level"] = int(st.get("raid_level") or 0)
    if not st.get("disks"):
        st["disks"] = RAID_MIN.get(st["raid_level"], 2)
    st["disks"] = int(st["disks"])
    pool = st.get("disk_pool") or DEFAULTS["storage"]["disk_pool"]
    if st["disks"] > len(pool):
        raise ValueError(f"need {st['disks']} disks, pool has {len(pool)}")
    st["devices"] = list(pool[: st["disks"]])
    st["devices_str"] = " ".join(st["devices"])
    st["md"] = st.get("md") or "/dev/md0"
    st["mount"] = st.get("mount") or f"/raid{st['raid_level']}"
    st["raid_name"] = f"RAID {st['raid_level']}"

    nfs = v["nfs"]
    nfs["export"] = nfs.get("export") or f"{st['mount']}/nfs"
    nfs["server"] = nfs.get("server") or v["hosts"]["hq-srv"]
    nfs["client_host"] = nfs.get("client_host") or v["hosts"]["hq-cli"]

    ntp = v["ntp"]
    ntp["server"] = ntp.get("server") or v["hosts"]["isp"]

    v["modules"] = [int(m) for m in v["modules"]]
    return v


def flatten(data, prefix=""):
    """Flatten nested dicts to dotted keys. Lists become space-joined strings."""
    out = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, name + "."))
        elif isinstance(value, (list, tuple)):
            out[name] = " ".join(str(x) for x in value)
        else:
            out[name] = "" if value is None else str(value)
    return out


def render(text, flat):
    if not text:
        return text

    def sub(match):
        key = match.group(1)
        if key not in flat:
            raise KeyError(f"unknown placeholder {{{{ {key} }}}}")
        return flat[key]

    return PLACEHOLDER.sub(sub, text)


def render_obj(value, flat):
    if isinstance(value, str):
        return render(value, flat)
    if isinstance(value, list):
        return [render_obj(v, flat) for v in value]
    if isinstance(value, dict):
        return {k: render_obj(v, flat) for k, v in value.items()}
    return value


def matches(condition, flat):
    """condition = {"storage.raid_level": [0, 1]} - every key must match."""
    for key, allowed in (condition or {}).items():
        if key not in flat:
            return False
        if isinstance(allowed, (list, tuple)):
            if flat[key] not in [str(a) for a in allowed]:
                return False
        elif flat[key] != str(allowed):
            return False
    return True
