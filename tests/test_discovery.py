"""Finding the Topaz installation, on this platform and on the one nobody has tried.

Discovery is the first thing that runs and the first thing that can go wrong, and until
now it had no tests at all — it was only ever exercised by running against the real
installation on one Windows machine. Two things needed covering.

**The safety property.** A candidate is accepted only once its ffmpeg actually reports
``tvai_up``. That is not a detail: a plain system FFmpeg on PATH looks exactly like the
real thing right up to the moment a Topaz filter is requested, and accepting one would
turn a clear "not found" into a confusing failure several minutes into a render.

**The other platform.** The README says Windows, and section 6 says Windows, because
Windows is the only machine this has ever run on. But "we only tested Windows" and "it
cannot work anywhere else" are different claims, and the code had never been asked which
one it makes. The answers are in ``test_macos_*`` below, and they are not flattering:
outside Windows there are **no automatic candidates at all**, so the explicit path and
the environment variables are the only way in. That is now written down rather than
assumed, and the messages say so.
"""

import os
import types
from pathlib import Path

import pytest

from topaz_video import discovery
from topaz_video.errors import TopazNotFoundError


FFMPEG_VERSION = (
    "ffmpeg version 8.1 Copyright (c) 2000-2025 the FFmpeg developers\n"
    "  configuration: --disable-decoder=h264 --disable-decoder=hevc\n"
)
TVAI_FILTERS = (
    " ... tvai_cpe          V->V       Topaz camera pose estimation\n"
    " ... tvai_fi           V->V       Topaz frame interpolation\n"
    " ... tvai_pe           V->V       Topaz parameter estimation\n"
    " ... tvai_stb          V->V       Topaz stabilisation\n"
    " ... tvai_up           V->V       Topaz upscale\n"
)
PLAIN_FILTERS = (
    " ... scale             V->V       Scale the input video size\n"
    " ... crop              V->V       Crop the input video\n"
)


@pytest.fixture(autouse=True)
def clean_cache():
    """The finder memoises. Without this every test would see the first one's answer."""
    discovery.clear_cache()
    yield
    discovery.clear_cache()


@pytest.fixture
def no_environment(monkeypatch):
    """Neither this machine's real Topaz nor its environment may leak into a test.

    Three separate leaks, and the first run of this file hit all three. Clearing the
    environment variables is the obvious one. The registry sweep is the second. The
    third is the subtle one: ``_candidate_roots`` ends with a hard-coded sweep of
    ``C:`` to ``H:`` and ``_model_dir_candidates`` with a hard-coded ``C:/ProgramData``,
    and on the machine this was written on **both of those exist and hold the real
    installation**. A test asserting "nothing was found" passed the real thing instead.
    Redirecting the two subdirectory constants is what actually silences them.
    """
    for var in discovery._ENV_INSTALL_VARS + discovery._ENV_MODEL_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "ProgramData"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(discovery, "_registry_roots", lambda: iter(()))
    monkeypatch.setattr(discovery, "_APP_SUBDIR",
                        os.path.join("Topaz Labs LLC", "No Such Product For Tests"))
    monkeypatch.setattr(discovery, "_MODEL_SUBDIR",
                        os.path.join("Topaz Labs LLC", "No Such Product For Tests",
                                     "models"))


def make_install(root: Path, *, ffprobe: bool = True, windows: bool | None = None) -> Path:
    """A directory shaped like a Topaz installation.

    ``windows`` defaults to whatever platform the suite is running on, because
    ``_inspect`` looks for ``ffmpeg.exe`` or ``ffmpeg`` depending on ``os.name``. Fixing
    it to ``.exe`` made every one of these tests pass on Windows and fail on a Linux CI
    runner — for a reason that has nothing to do with the code under test. Pass it
    explicitly only where the platform is the point.
    """
    root.mkdir(parents=True, exist_ok=True)
    if windows is None:
        windows = os.name == "nt"
    suffix = ".exe" if windows else ""
    (root / f"ffmpeg{suffix}").write_text("binary", encoding="utf-8")
    if ffprobe:
        (root / f"ffprobe{suffix}").write_text("binary", encoding="utf-8")
    return root


def fake_run(tvai: bool = True):
    """Stand in for the ffmpeg probes, so no subprocess runs during the suite."""
    def run(cmd, timeout=30):
        argument = cmd[-1] if cmd else ""
        if argument == "-version":
            return FFMPEG_VERSION
        if argument == "-filters":
            return TVAI_FILTERS if tvai else PLAIN_FILTERS
        return ""
    return run


# --- the safety property ------------------------------------------------------------

def test_an_ffmpeg_without_tvai_is_refused(tmp_path, monkeypatch, no_environment):
    """The whole point of probing rather than trusting the path.

    A system FFmpeg is indistinguishable from Topaz's until a tvai filter is asked for.
    Accepting one turns "no Topaz installed" into a render that dies much later with a
    message about a filter nobody recognises.
    """
    root = make_install(tmp_path / "not-topaz")
    monkeypatch.setattr(discovery, "_run", fake_run(tvai=False))
    with pytest.raises(TopazNotFoundError):
        discovery.find_install(str(root))


def test_an_ffmpeg_with_tvai_is_accepted(tmp_path, monkeypatch, no_environment):
    root = make_install(tmp_path / "topaz")
    monkeypatch.setattr(discovery, "_run", fake_run(tvai=True))
    install = discovery.find_install(str(root))
    assert install.root == root
    assert install.has_tvai
    assert "tvai_up" in install.filters
    assert "tvai_stb" in install.filters
    assert install.ffmpeg_version.startswith("ffmpeg version 8.1")
    assert "--disable-decoder=h264" in install.build_flags


def test_a_directory_without_ffmpeg_is_refused(tmp_path, monkeypatch, no_environment):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(discovery, "_run", fake_run())
    with pytest.raises(TopazNotFoundError):
        discovery.find_install(str(empty))


def test_a_missing_ffprobe_is_not_fatal(tmp_path, monkeypatch, no_environment):
    """ffprobe is used for reporting only; the filters live in ffmpeg."""
    root = make_install(tmp_path / "topaz", ffprobe=False)
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install(str(root)).ffprobe is None


def test_the_not_found_message_names_a_way_forward(tmp_path, monkeypatch,
                                                   no_environment):
    monkeypatch.setattr(discovery, "_run", fake_run(tvai=False))
    with pytest.raises(TopazNotFoundError) as caught:
        discovery.find_install(str(tmp_path / "nowhere"))
    text = str(caught.value)
    assert "tvai_up" in text, "the message has to say what actually qualifies"
    assert "TOPAZ_VIDEO_LOCAL_DIR" in text, "and how to point it somewhere by hand"
    assert "Searched:" in text


# --- where it looks -----------------------------------------------------------------

def test_the_explicit_path_wins(tmp_path, monkeypatch, no_environment):
    chosen = make_install(tmp_path / "chosen")
    other = make_install(tmp_path / "other")
    monkeypatch.setenv("TOPAZ_VIDEO_LOCAL_DIR", str(other))
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install(str(chosen)).root == chosen


def test_the_environment_variables_are_honoured_in_order(tmp_path, monkeypatch,
                                                         no_environment):
    first = make_install(tmp_path / "first")
    second = make_install(tmp_path / "second")
    monkeypatch.setenv("TOPAZ_VIDEO_LOCAL_DIR", str(first))
    monkeypatch.setenv("TVAI_DIR", str(second))
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install().root == first


def test_a_broken_environment_variable_does_not_stop_the_search(tmp_path, monkeypatch,
                                                                no_environment):
    """Pointing the variable at a stale path must fall through, not fail outright."""
    real = make_install(tmp_path / "real")
    monkeypatch.setenv("TOPAZ_VIDEO_LOCAL_DIR", str(tmp_path / "deleted"))
    monkeypatch.setenv("TVAI_DIR", str(real))
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install().root == real


def test_the_result_is_cached_and_refresh_clears_it(tmp_path, monkeypatch,
                                                    no_environment):
    root = make_install(tmp_path / "topaz")
    calls = []

    def counting(cmd, timeout=30):
        calls.append(cmd[-1] if cmd else "")
        return fake_run()(cmd, timeout)

    monkeypatch.setattr(discovery, "_run", counting)
    discovery.find_install(str(root))
    after_first = len(calls)
    discovery.find_install(str(root))
    assert len(calls) == after_first, "a second lookup must not probe again"
    discovery.find_install(str(root), refresh=True)
    assert len(calls) > after_first, "refresh has to actually re-probe"


# --- the model directory ------------------------------------------------------------

def test_the_model_directory_comes_from_the_environment_first(tmp_path, monkeypatch,
                                                              no_environment):
    root = make_install(tmp_path / "topaz")
    models = tmp_path / "models"
    models.mkdir()
    (models / "prob-4.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TVAI_MODEL_DIR", str(models))
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install(str(root)).model_dir == models


def test_a_model_directory_without_json_is_not_one(tmp_path, monkeypatch,
                                                   no_environment):
    """An empty folder of the right name is the trap here: it exists, so a bare
    is_dir() check would take it and the catalogue would silently come back empty."""
    root = make_install(tmp_path / "topaz")
    empty = tmp_path / "models"
    empty.mkdir()
    (empty / "readme.txt").write_text("no models here", encoding="utf-8")
    monkeypatch.setenv("TVAI_MODEL_DIR", str(empty))
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install(str(root)).model_dir is None


def test_models_beside_the_binary_are_the_last_resort(tmp_path, monkeypatch,
                                                      no_environment):
    root = make_install(tmp_path / "topaz")
    beside = root / "models"
    beside.mkdir()
    (beside / "prob-4.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(discovery, "_run", fake_run())
    assert discovery.find_install(str(root)).model_dir == beside


def test_the_environment_carries_both_model_variables(tmp_path, monkeypatch,
                                                      no_environment):
    """Topaz's ffmpeg reports 'Model not found' for models that are plainly installed
    unless both are set — that cost an afternoon when reproducing a command by hand."""
    root = make_install(tmp_path / "topaz")
    models = root / "models"
    models.mkdir()
    (models / "prob-4.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(discovery, "_run", fake_run())
    env = discovery.find_install(str(root)).env()
    assert env["TVAI_MODEL_DIR"] == str(models)
    assert env["TVAI_MODEL_DATA_DIR"] == str(models)
    assert env["PATH"].startswith(str(root)), (
        "Topaz ships its own DLLs in the install root; without it on PATH the filters "
        "fail to load")


# --- the platform nobody has tried --------------------------------------------------

@pytest.fixture
def posix(monkeypatch):
    """Pretend this is macOS or Linux, for ``discovery`` only.

    Setting ``os.name`` globally is the obvious way and it does not work: ``pathlib``
    reads it to decide whether ``Path`` means ``WindowsPath`` or ``PosixPath``, so every
    Path built afterwards raises "cannot instantiate 'PosixPath' on your system". A stub
    bound into this one module changes the platform for the code under test and nothing
    else.
    """
    monkeypatch.setattr(discovery, "os", _platform_stub("posix"))


@pytest.fixture
def windows(monkeypatch):
    """The mirror image, so a test about Windows behaviour states it rather than
    relying on the runner happening to be Windows. CI runs this suite on Linux too."""
    monkeypatch.setattr(discovery, "os", _platform_stub("nt"))


def _platform_stub(name: str):
    return types.SimpleNamespace(
        name=name, environ=os.environ, path=os.path, pathsep=os.pathsep,
    )


def test_macos_finds_nothing_on_its_own(monkeypatch, no_environment, posix):
    """**This is a finding, not a passing feature.**

    With no explicit path and no environment variable, the candidate list outside
    Windows contains only Windows locations — the ProgramFiles variables (absent) and a
    hard-coded sweep of drive letters C: to H:. On macOS, Topaz Video AI installs inside
    an .app bundle and its models live under /Library/Application Support; neither is
    looked for.

    So the honest statement is: macOS is not unsupported by accident of an untested code
    path, it is unimplemented. The explicit path and TOPAZ_VIDEO_LOCAL_DIR work, and
    nothing else does. The test exists so that adding macOS support makes it fail.
    """
    candidates = list(discovery._candidate_roots(None))
    posix_like = [c for c in candidates
                  if str(c).startswith("/") and "Program Files" not in str(c)]
    assert not posix_like, (
        "a POSIX candidate appeared, so macOS support has been started — update this "
        f"test and section 5.4 of the handover: {posix_like}")


def test_macos_never_touches_the_registry(monkeypatch, no_environment, posix):
    """_registry_roots imports winreg, which does not exist off Windows. It is guarded
    by os.name, and this is the guard's test."""
    def explode():
        raise AssertionError("the registry was swept on a non-Windows platform")

    monkeypatch.setattr(discovery, "_registry_roots", lambda: explode())
    list(discovery._candidate_roots(None))  # must not raise


def test_macos_looks_for_an_ffmpeg_without_the_exe_suffix(tmp_path, monkeypatch,
                                                          no_environment, posix):
    """The one part of the search that is already platform-aware."""
    root = make_install(tmp_path / "Topaz Video AI.app", windows=False)
    monkeypatch.setattr(discovery, "_run", fake_run())
    install = discovery.find_install(str(root))
    assert install.ffmpeg == root / "ffmpeg"
    assert install.ffprobe == root / "ffprobe"


def test_macos_can_be_pointed_at_an_installation_by_hand(tmp_path, monkeypatch,
                                                         no_environment, posix):
    """The route that does work, and therefore the one the message must recommend."""
    root = make_install(tmp_path / "Topaz Video AI.app" / "Contents" / "Resources",
                        windows=False)
    models = root / "models"
    models.mkdir()
    (models / "prob-4.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TOPAZ_VIDEO_LOCAL_DIR", str(root))
    monkeypatch.setattr(discovery, "_run", fake_run())
    install = discovery.find_install()
    assert install.root == root
    assert install.model_dir == models
    assert install.has_tvai


def test_windows_drive_letters_are_not_scanned_off_windows(monkeypatch, no_environment,
                                                           posix):
    """`C:/Program Files/...` is not a path on macOS.

    This one failed on its first run: the drive-letter sweep and the ProgramFiles
    variables sat outside the ``os.name == "nt"`` guard, so a Mac user's "Searched:"
    list would have been six Windows paths that cannot exist. Cheaper to fix the guard
    than to teach the test to accept it.
    """
    candidates = [str(c) for c in discovery._candidate_roots(None)]
    drive_letters = [c for c in candidates if len(c) > 1 and c[1] == ":"]
    assert not drive_letters, (
        "the drive-letter sweep still runs off Windows: " + ", ".join(drive_letters[:4]))


def test_the_message_off_windows_says_detection_is_windows_only(monkeypatch,
                                                                no_environment, posix):
    """Leaving a Mac user to work out that the empty search list means "unimplemented"
    rather than "not installed" is a support question waiting to happen."""
    monkeypatch.setattr(discovery, "_run", fake_run(tvai=False))
    with pytest.raises(TopazNotFoundError) as caught:
        discovery.find_install()
    text = str(caught.value)
    assert "Windows only" in text
    assert "TOPAZ_VIDEO_LOCAL_DIR" in text


def test_the_message_on_windows_does_not_carry_that_note(tmp_path, monkeypatch,
                                                         no_environment, windows):
    monkeypatch.setattr(discovery, "_run", fake_run(tvai=False))
    with pytest.raises(TopazNotFoundError) as caught:
        discovery.find_install(str(tmp_path / "nowhere"))
    assert "Windows only" not in str(caught.value)
