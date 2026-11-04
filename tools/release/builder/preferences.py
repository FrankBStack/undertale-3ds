"""Small, best-effort UI preferences in the builder's work folder only."""
import json
import math
import os
import tempfile


def load(work):
    try:
        with open(os.path.join(work, "ui-preferences.json"), encoding="utf-8") as source:
            value = json.load(source)
        result = {"boring": value.get("boring") is True} if isinstance(value, dict) else {"boring": False}
        if isinstance(value, dict) and isinstance(value.get('console'), str):
            try:
                from ftp_delivery import endpoint
                host, port = endpoint(value['console'])
                result['console'] = '%s:%d' % (host, port)
            except OSError:
                pass
        if isinstance(value, dict):
            if type(value.get('updates')) is bool:
                result['updates'] = value['updates']
            checks = value.get('update_checks')
            if isinstance(checks, dict):
                result['update_checks'] = {game: stamp for game, stamp in checks.items()
                    if game in ('undertale', 'deltarune') and type(stamp) in (int, float)
                    and math.isfinite(stamp) and stamp >= 0}
            notices = value.get('update_notices')
            if isinstance(notices, dict):
                result['update_notices'] = {game: notice for game, notice in notices.items()
                    if game in ('undertale', 'deltarune') and isinstance(notice, dict)
                    and all(isinstance(notice.get(key), str) and len(notice[key]) <= limit
                            for key, limit in (('version', 160), ('notes', 480), ('url', 500)))}
        return result
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {"boring": False}


def save(work, boring, console=None, *, updates=None, update_check=None, update_notice=None):
    temporary = None
    try:
        os.makedirs(work, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work,
                                         prefix=".ui-preferences-", delete=False) as target:
            temporary = target.name
            value = load(work)
            value['boring'] = bool(boring)
            if updates is not None:
                value['updates'] = bool(updates)
            if update_check is not None:
                game, stamp = update_check
                value.setdefault('update_checks', {})[game] = stamp
            if update_notice is not None:
                game, notice = update_notice
                value.setdefault('update_notices', {})[game] = notice
            if console is not None:
                from ftp_delivery import endpoint
                host, port = endpoint(console)
                value['console'] = '%s:%d' % (host, port)
            json.dump(value, target)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, os.path.join(work, "ui-preferences.json"))
        return True
    except OSError:
        return False
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
