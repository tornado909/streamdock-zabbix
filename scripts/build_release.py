"""Build an audit-friendly release from Git-tracked files only."""
from pathlib import Path
import hashlib
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION="1.0.0"
PREFIX="streamdock-zabbix-"+VERSION+"/"
OUTPUT=ROOT/"dist"
ZIP_NAME="streamdock-zabbix-v"+VERSION+"-rc1.zip"

def build():
    raw=subprocess.run(["git","ls-files","-z"],cwd=ROOT,stdout=subprocess.PIPE,check=True).stdout
    names=sorted(x.decode("utf-8") for x in raw.split(b"\0") if x)
    essential={"install.ps1","configure.ps1","uninstall.ps1","README.md","README.ru.md","LICENSE","SECURITY.md",
               "config.example.json","src/bridge.py","src/universal.py","src/universal_http.py",
               "plugin/com.streamdock.zabbix.sdPlugin/manifest.json"}
    if not essential.issubset(names):raise RuntimeError("Missing required files in Git index")
    if not names:raise RuntimeError("No files staged for release")
    OUTPUT.mkdir(exist_ok=True)
    destination=OUTPUT/ZIP_NAME
    with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in names:
            path=ROOT/name
            parts=[s.lower() for s in Path(name).parts]
            if any(s in (".git","logs","profiles","backup","backups","__pycache__") for s in parts):
                raise RuntimeError("Private directory in archive")
            if name.lower().endswith((".dpapi",".key",".pem",".pfx",".p12",".sdprofile")) or Path(name).name.lower() in ("settings.json",".env",".env.local"):
                raise RuntimeError("Private file in archive")
            if not path.is_file() or path.is_symlink():
                raise RuntimeError("Non-regular tracked file")
            info=zipfile.ZipInfo(PREFIX+name.replace("\\","/"),date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100644<<16)
            archive.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:raise RuntimeError("ZIP CRC error")
        if len(archive.namelist())!=len(names):raise RuntimeError("ZIP file list changed")
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum=destination.with_suffix(".sha256")
    checksum.write_text(digest+"  "+destination.name+"\n",encoding="ascii")
    print("ARCHIVE",destination)
    print("FILES",len(names))
    print("SIZE_BYTES",destination.stat().st_size)
    print("SHA256",digest)
    print("CHECKSUM",checksum)

if __name__=="__main__":
    try:build()
    except Exception as exc:
        print("BUILD FAILED:",str(exc),file=sys.stderr)
        sys.exit(1)
