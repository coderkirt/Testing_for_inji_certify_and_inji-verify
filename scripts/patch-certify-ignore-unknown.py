"""Patch Certify 1.0.0-alpha.1 for the local OID4VCI 1.0 issuer plan.

- CredentialRequest ignores unknown JSON fields.
- JwtProofValidator does not require proof iss to match an empty client_id.
- DPoP binding, display metadata, and unknown-credential errors are compiled in the same pass.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".tmp-certify-patch"
FAT_JAR = WORK / "certify-service.jar"
CORE_NAME = "BOOT-INF/lib/certify-core-1.0.0-alpha.1.jar"
REQUEST_SRC = ROOT / "compose" / "certify" / "patch" / "CredentialRequest.java"
DISPLAY_DTO_SRC = ROOT / "compose" / "certify" / "patch" / "MetaDataDisplayDTO.java"
PROOF_SRC = ROOT / "compose" / "certify" / "patch" / "JwtProofValidator.java"
ISSUANCE_SRC = ROOT / "compose" / "certify" / "patch" / "CertifyIssuanceServiceImpl.java"
UTIL_SRC = ROOT / "compose" / "certify" / "patch" / "VCIssuanceUtil.java"
DISPLAY_SRC = ROOT / "compose" / "certify" / "patch" / "MetaDataDisplay.java"
TOKEN_SRC = ROOT / "compose" / "certify" / "patch" / "AccessTokenJwtUtil.java"
DPOP_SRC = ROOT / "compose" / "certify" / "patch" / "DpopProofs.java"
DPOP_FILTER_SRC = ROOT / "compose" / "certify" / "patch" / "DpopBoundAccessFilter.java"
PROOF_CLASS = "BOOT-INF/classes/io/mosip/certify/proof/JwtProofValidator.class"
SERVICE_CLASS_PREFIXES = (
    "BOOT-INF/classes/io/mosip/certify/services/CertifyIssuanceServiceImpl",
    "BOOT-INF/classes/io/mosip/certify/utils/VCIssuanceUtil",
    "BOOT-INF/classes/io/mosip/certify/entity/attributes/MetaDataDisplay",
    "BOOT-INF/classes/io/mosip/certify/utils/AccessTokenJwtUtil",
)
DEFAULT_CONTAINER = "inji-openid-conformance-certify-1"
JAR_IN_CONTAINER = "/home/inji/certify-service.jar"
PROOF_LIB_PREFIXES = (
    "BOOT-INF/lib/nimbus-jose-jwt-",
    "BOOT-INF/lib/commons-lang3-",
    "BOOT-INF/lib/spring-beans-",
    "BOOT-INF/lib/spring-context-",
    "BOOT-INF/lib/spring-core-",
    "BOOT-INF/lib/spring-jcl-",
    "BOOT-INF/lib/slf4j-api-",
)


def find_javac() -> str:
    override = os.environ.get("JAVAC")
    if override and Path(override).is_file():
        return override
    found = shutil.which("javac")
    if found:
        return found
    fallback = Path(r"C:\Program Files\Java\jdk-26.0.1\bin\javac.exe")
    if fallback.is_file():
        return str(fallback)
    print("javac not found. Install JDK 21+ or set JAVAC.", file=sys.stderr)
    return ""


def extract(z: zipfile.ZipFile, name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(z.read(name))


def main() -> int:
    if not FAT_JAR.exists():
        print(f"missing {FAT_JAR}", file=sys.stderr)
        return 1
    if not REQUEST_SRC.exists():
        print(f"missing {REQUEST_SRC}", file=sys.stderr)
        return 1
    if not PROOF_SRC.exists():
        print(f"missing {PROOF_SRC}", file=sys.stderr)
        return 1
    javac = find_javac()
    if not javac:
        return 1

    with zipfile.ZipFile(FAT_JAR) as outer:
        extract(outer, "BOOT-INF/lib/jackson-annotations-2.15.4.jar", WORK / "jackson-annotations.jar")
        extract(outer, "BOOT-INF/lib/jakarta.validation-api-3.0.2.jar", WORK / "jakarta.validation-api.jar")
        core_bytes = outer.read(CORE_NAME)

    core_dir = WORK / "core-extract"
    if core_dir.exists():
        shutil.rmtree(core_dir)
    core_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(core_bytes)) as core:
        core.extractall(core_dir)

    src = REQUEST_SRC
    classes = WORK / "patched-classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    cp = os.pathsep.join(
        [
            str(WORK / "jackson-annotations.jar"),
            str(WORK / "jakarta.validation-api.jar"),
            str(core_dir),
        ]
    )
    cmd = [
        javac,
        "-encoding",
        "UTF-8",
        "--release",
        "21",
        "-cp",
        cp,
        "-d",
        str(classes),
        str(src),
        str(DISPLAY_DTO_SRC),
    ]
    subprocess.check_call(cmd)

    boot_classes = WORK / "boot-classes"
    if boot_classes.exists():
        shutil.rmtree(boot_classes)
    boot_classes.mkdir()
    proof_jars: list[Path] = []
    with zipfile.ZipFile(FAT_JAR) as outer:
        for name in outer.namelist():
            if name.startswith("BOOT-INF/classes/") and not name.endswith("/"):
                dest = boot_classes / name[len("BOOT-INF/classes/") :]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(outer.read(name))
            elif name.startswith(PROOF_LIB_PREFIXES):
                dest = WORK / "proof-libs" / Path(name).name
                extract(outer, name, dest)
                proof_jars.append(dest)

    proof_classes = WORK / "patched-proof"
    if proof_classes.exists():
        shutil.rmtree(proof_classes)
    proof_classes.mkdir()
    proof_cp = os.pathsep.join([str(boot_classes), str(core_dir), *(str(jar) for jar in proof_jars)])
    subprocess.check_call(
        [
            javac,
            "-encoding",
            "UTF-8",
            "--release",
            "21",
            "-cp",
            proof_cp,
            "-d",
            str(proof_classes),
            str(PROOF_SRC),
        ]
    )
    patched_proof = proof_classes / "io/mosip/certify/proof/JwtProofValidator.class"

    libs = WORK / "all-libs"
    if libs.exists():
        shutil.rmtree(libs)
    libs.mkdir()
    with zipfile.ZipFile(FAT_JAR) as outer:
        for name in outer.namelist():
            if name.startswith("BOOT-INF/lib/") and name.endswith(".jar"):
                dest = libs / Path(name).name
                dest.write_bytes(outer.read(name))
    service_classes = WORK / "patched-service"
    if service_classes.exists():
        shutil.rmtree(service_classes)
    service_classes.mkdir()
    service_cp = os.pathsep.join([str(classes), str(boot_classes), str(libs / "*")])
    subprocess.check_call(
        [
            javac,
            "-encoding",
            "UTF-8",
            "--release",
            "21",
            "-cp",
            service_cp,
            "-d",
            str(service_classes),
            str(ISSUANCE_SRC),
            str(UTIL_SRC),
            str(DISPLAY_SRC),
            str(TOKEN_SRC),
            str(DPOP_SRC),
            str(DPOP_FILTER_SRC),
        ]
    )

    patched_class = classes / "io/mosip/certify/core/dto/CredentialRequest.class"
    dest_class = core_dir / "io/mosip/certify/core/dto/CredentialRequest.class"
    shutil.copyfile(patched_class, dest_class)

    new_core = WORK / "certify-core-1.0.0-alpha.1.jar"
    with zipfile.ZipFile(io.BytesIO(core_bytes)) as orig_core, zipfile.ZipFile(
        new_core, "w"
    ) as out_core:
        for info in orig_core.infolist():
            if info.is_dir():
                out_core.writestr(info, b"")
                continue
            patched_file = classes / info.filename
            if patched_file.is_file():
                data = patched_file.read_bytes()
            else:
                data = orig_core.read(info.filename)
            out_core.writestr(info, data)

    patched_fat = WORK / "certify-service-patched.jar"
    with zipfile.ZipFile(FAT_JAR, "r") as src_zip, zipfile.ZipFile(
        patched_fat, "w"
    ) as dst_zip:
        for info in src_zip.infolist():
            if info.filename.startswith(SERVICE_CLASS_PREFIXES):
                continue
            if info.filename == CORE_NAME:
                data = new_core.read_bytes()
            elif info.filename == PROOF_CLASS:
                data = patched_proof.read_bytes()
            else:
                data = src_zip.read(info.filename)
            dst_zip.writestr(info, data)
        for class_file in service_classes.rglob("*.class"):
            rel = class_file.relative_to(service_classes).as_posix()
            dst_zip.writestr(f"BOOT-INF/classes/{rel}", class_file.read_bytes())

    print(patched_fat)
    return 0


def wait_healthy(container: str, timeout: int = 240) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        status = (proc.stdout or "").strip()
        if status == "healthy":
            print(f"{container} is healthy")
            return
        if status in {"exited", "dead"}:
            raise SystemExit(f"{container} is {status}")
        time.sleep(5)
    raise SystemExit(f"Timed out waiting for {container} to become healthy")


def install(container: str) -> int:
    """Copy the image jar out, patch it, and restart that container only."""
    WORK.mkdir(parents=True, exist_ok=True)
    print(f"Waiting for {container} before copying the issuer jar")
    wait_healthy(container)
    subprocess.check_call(["docker", "cp", f"{container}:{JAR_IN_CONTAINER}", str(FAT_JAR)])
    code = main()
    if code != 0:
        return code
    patched = WORK / "certify-service-patched.jar"
    subprocess.check_call(["docker", "cp", str(patched), f"{container}:{JAR_IN_CONTAINER}"])
    subprocess.check_call(["docker", "restart", container])
    wait_healthy(container)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Patch the Certify 1.0 issuer jar for the OID4VCI plan")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy the jar from the running Certify container, patch it, and restart that container",
    )
    parser.add_argument("--container", default=os.environ.get("CERTIFY_CONTAINER", DEFAULT_CONTAINER))
    args = parser.parse_args()
    if args.install:
        raise SystemExit(install(args.container))
    raise SystemExit(main())
