import os
import shutil
import time
TIME_TOLERANCE = 2  # seconds


def newer(src, dst):
    return os.path.getmtime(src) - os.path.getmtime(dst) > TIME_TOLERANCE

def sync_one_way(source, destination, delete_extras=True, logger=print, stop_event=None):

    def log(msg):
        if logger:
            logger(msg)

    start_time = time.time()
    bytes_transferred = 0

    log("🔍 Validating paths...")

    if stop_event and stop_event.is_set():
        log("🛑 Stopped before start")
        return

    if not os.path.exists(source):
        raise Exception(f"Source not accessible: {source}")

    if not os.path.exists(destination):
        os.makedirs(destination, exist_ok=True)

    copied = 0
    updated = 0
    deleted = 0

    # ========= SOURCE ➜ DESTINATION =========
    for root, _, files in os.walk(source):

        if stop_event and stop_event.is_set():
            log("🛑 Stopping immediately...")
            return

        rel = os.path.relpath(root, source)
        dest_root = os.path.join(destination, rel)
        os.makedirs(dest_root, exist_ok=True)

        for file in files:

            if stop_event and stop_event.is_set():
                log("🛑 Stopping immediately...")
                return

            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_root, file)

            size = os.path.getsize(src_file)

            if not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)
                copied += 1
                bytes_transferred += size
                log(f"➕ Copied → {src_file}")

            elif newer(src_file, dst_file):
                shutil.copy2(src_file, dst_file)
                updated += 1
                bytes_transferred += size
                log(f"🔄 Updated → {src_file}")

    # ========= DELETE EXTRAS =========
    if delete_extras:
        for root, _, files in os.walk(destination):

            if stop_event and stop_event.is_set():
                log("🛑 Stopping immediately...")
                return

            rel = os.path.relpath(root, destination)
            src_root = os.path.join(source, rel)

            for file in files:

                if stop_event and stop_event.is_set():
                    log("🛑 Stopping immediately...")
                    return

                dst_file = os.path.join(root, file)
                src_file = os.path.join(src_root, file)

                if not os.path.exists(src_file):
                    os.remove(dst_file)
                    deleted += 1
                    log(f"🗑 Deleted → {dst_file}")

    # ========= SPEED CALCULATION =========

    duration = time.time() - start_time
    mb = bytes_transferred / (1024 * 1024)

    speed = mb / duration if duration > 0 else 0

    log("📊 Sync Summary:")
    log(f"   ➕ Copied : {copied}")
    log(f"   🔄 Updated: {updated}")
    log(f"   🗑 Deleted: {deleted}")
    log(f"   📦 Data   : {mb:.2f} MB")
    log(f"   ⭐ Speed  : {speed:.2f} MB/s")

    log("✅ Sync Completed")