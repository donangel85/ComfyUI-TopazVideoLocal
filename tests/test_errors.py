"""Regression tests for error classification.

Central case: the real Intel QSV decoder failure contains the words "not supported".
The previous node matched on that substring and concluded the *encoder* had failed,
then swapped in h264_mf, which of course could not fix a decoder problem.
"""

import sys
from pathlib import Path


from topaz_studio.errors import (  # noqa: E402
    TopazDecodeError,
    TopazEncodeError,
    TopazLicenseError,
    TopazModelError,
    TopazProcessError,
    classify,
    is_encoder_failure,
)

# Verbatim from the handover document, section 3.
QSV_DECODER_FAILURE = """
[h264_qsv] Error creating a MFX session: -9.
[h264_qsv] The current mfx implementation is not supported, try next mfx implementation.
[h264_qsv] Error initializing an MFX session
[h264_qsv] Error decoding header
Conversion failed!
"""

REAL_ENCODER_FAILURE = """
[h264_nvenc @ 000001] No capable devices found
[vost#0:0/h264_nvenc] Error while opening encoder - maybe incorrect parameters
Conversion failed!
"""


def test_qsv_decoder_failure_is_not_an_encoder_failure():
    """The exact bug from section 5."""
    assert is_encoder_failure(QSV_DECODER_FAILURE, "h264_nvenc") is False


def test_qsv_decoder_failure_classifies_as_decode_error():
    err = classify(1, QSV_DECODER_FAILURE, output_encoder="h264_nvenc")
    assert isinstance(err, TopazDecodeError)


def test_real_encoder_failure_is_recognised():
    assert is_encoder_failure(REAL_ENCODER_FAILURE, "h264_nvenc") is True
    err = classify(1, REAL_ENCODER_FAILURE, output_encoder="h264_nvenc")
    assert isinstance(err, TopazEncodeError)


def test_encoder_failure_needs_a_known_encoder():
    """With no encoder in the command, an encoder fallback is never justified."""
    assert is_encoder_failure(REAL_ENCODER_FAILURE, None) is False
    err = classify(1, REAL_ENCODER_FAILURE, output_encoder=None)
    assert isinstance(err, TopazProcessError)


def test_licence_message_classifies_as_licence_error():
    err = classify(1, "Topaz Video: no valid license found", output_encoder=None)
    assert isinstance(err, TopazLicenseError)


def test_model_configuration_failure():
    err = classify(1, "[Parsed_tvai_up_0] Failed to configure output pad on "
                      "Parsed_tvai_up_0", output_encoder=None, model="rhea-1")
    assert isinstance(err, TopazModelError)
    assert "rhea-1" in err.message


def test_short_batch_crash_is_explained():
    """1-3 frames crash tvai_up with an access violation; say why."""
    err = classify(3221225477, "", output_encoder=None, model="prob-4",
                   frame_count=2, min_frames=4)
    assert isinstance(err, TopazModelError)
    assert "too short" in err.message
    assert "at least 4" in err.message


def test_auth_token_is_scrubbed_from_stderr():
    leaked = ('[TopazAuthManager]parseAuth got details{"auth_studio":'
              '"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abc"}\n'
              "Conversion failed!")
    err = classify(1, leaked, output_encoder=None)
    assert "eyJhbGciOiJSUzI1NiJ9" not in err.stderr
    assert "TopazAuthManager" not in err.stderr
    assert "eyJhbGciOiJSUzI1NiJ9" not in err.detailed()


def test_unknown_failure_keeps_stderr_for_debugging():
    err = classify(1, "something unexpected happened", output_encoder=None)
    assert isinstance(err, TopazProcessError)
    assert "something unexpected" in err.stderr
