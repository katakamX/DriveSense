from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drivesense_contracts import TelemetryFrame, TelemetrySink, TelemetrySource, TripMeta
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import DEMO_DRIVE
from drivesense_sim.input.providers import ScriptedInputProvider, ScriptStep
from drivesense_sim.source import SimulatorTelemetrySource
from drivesense_sim.telemetry.mapper import TelemetryMapper
from drivesense_sim.telemetry.sinks import JsonlSink, MemorySink, NullSink, read_jsonl
from tests.conftest import make_session

STARTED_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def test_frame_reports_the_actual_simulated_state(spec: VehicleSpec) -> None:
    """Telemetry must be a reading of vehicle state, never independently
    generated."""
    config = SimConfig()
    session = make_session(
        [ScriptStep(0.1, shift_up=True), ScriptStep(4.0, throttle=1.0, steer=0.5)], spec, config
    )
    session.advance_seconds(4.1)
    state = session.state

    mapper = TelemetryMapper(config, "trip-x", STARTED_AT)
    frame = mapper.to_frame(state)

    assert frame.speed_kph == pytest.approx(state.speed_kph)
    assert frame.engine_rpm == pytest.approx(state.engine_rpm)
    assert frame.accel_ms2 == pytest.approx(state.accel_ms2)
    assert frame.throttle_pct == pytest.approx(state.throttle * 100)
    assert frame.brake_pct == pytest.approx(state.brake * 100)
    assert frame.clutch_pct == pytest.approx(state.clutch * 100)
    assert frame.engine_load_pct == pytest.approx(state.engine_load * 100)
    assert frame.gear == state.gear
    assert frame.steering_deg == pytest.approx(state.steering_deg)
    assert frame.yaw_rate_dps == pytest.approx(math.degrees(state.yaw_rate))
    assert frame.distance_m == pytest.approx(state.distance_m)
    assert frame.coolant_c == pytest.approx(state.coolant_c)


def test_timestamps_are_simulated_not_wall_clock(spec: VehicleSpec) -> None:
    config = SimConfig()
    mapper = TelemetryMapper(config, "trip-x", STARTED_AT)
    session = make_session([ScriptStep(2.0)], spec, config)
    session.advance_seconds(2.0)

    frame = mapper.to_frame(session.state)

    assert frame.sim_t == pytest.approx(2.0, abs=1e-6)
    assert (frame.ts - STARTED_AT).total_seconds() == pytest.approx(2.0, abs=1e-6)


def test_sequence_numbers_increment(spec: VehicleSpec) -> None:
    session = make_session([ScriptStep(1.0)], spec, SimConfig())
    frames = session.advance_seconds(1.0)

    assert [frame.seq for frame in frames] == list(range(len(frames)))


def test_sampling_rate_matches_configuration(spec: VehicleSpec) -> None:
    config = SimConfig(telemetry_hz=10.0, physics_hz=120.0)
    session = make_session([ScriptStep(5.0)], spec, config)

    frames = session.advance_seconds(5.0)

    assert len(frames) == 50


def test_noise_is_off_by_default_and_reproducible_when_on(spec: VehicleSpec) -> None:
    session = make_session([ScriptStep(1.0, throttle=0.5)], spec, SimConfig())
    session.advance_seconds(1.0)
    state = session.state

    clean = TelemetryMapper(SimConfig(), "t", STARTED_AT).to_frame(state)
    assert clean.engine_rpm == pytest.approx(state.engine_rpm)

    noisy_config = SimConfig(sensor_noise_enabled=True, sensor_noise_seed=99)
    first = TelemetryMapper(noisy_config, "t", STARTED_AT).to_frame(state)
    second = TelemetryMapper(noisy_config, "t", STARTED_AT).to_frame(state)

    assert first.engine_rpm != pytest.approx(state.engine_rpm)
    assert first.engine_rpm == pytest.approx(second.engine_rpm)


def test_gps_is_derived_from_position(spec: VehicleSpec) -> None:
    config = SimConfig()
    session = make_session(
        [ScriptStep(0.1, shift_up=True), ScriptStep(5.0, throttle=1.0)], spec, config
    )
    session.advance_seconds(5.1)

    frame = TelemetryMapper(config, "t", STARTED_AT).to_frame(session.state)

    assert frame.lat is not None and frame.lon is not None
    assert frame.lat != config.origin_lat
    assert session.state.distance_m > 0.0


# --- Sinks ------------------------------------------------------------------


def test_protocol_conformance() -> None:
    assert isinstance(NullSink(), TelemetrySink)
    assert isinstance(MemorySink(), TelemetrySink)
    assert isinstance(JsonlSink(), TelemetrySink)
    assert isinstance(SimulatorTelemetrySource(ScriptedInputProvider(DEMO_DRIVE)), TelemetrySource)


def test_jsonl_round_trip_and_sidecar(tmp_path: Path, spec: VehicleSpec) -> None:
    config = SimConfig()
    session = make_session(
        [ScriptStep(0.1, shift_up=True), ScriptStep(3.0, throttle=0.8)], spec, config
    )
    sink = JsonlSink(tmp_path)
    session.attach_sink(sink)
    session.advance_seconds(3.1)
    session.close()

    assert sink.path is not None and sink.meta_path is not None
    frames = read_jsonl(sink.path)

    assert len(frames) == sink.frames_written == session.frames_emitted
    assert all(isinstance(frame, TelemetryFrame) for frame in frames)
    assert frames[-1].speed_kph > 0.0

    meta = TripMeta.model_validate(json.loads(sink.meta_path.read_text(encoding="utf-8")))
    assert meta.trip_id == session.trip_id
    assert meta.sample_rate_hz == config.telemetry_hz
    assert meta.generator == "drivesense-sim"
    assert meta.vehicle["name"] == spec.name


def test_writing_before_open_is_an_error(spec: VehicleSpec) -> None:
    config = SimConfig()
    frame = TelemetryMapper(config, "t", STARTED_AT).to_frame(
        make_session([ScriptStep(0.1)], spec, config).state
    )

    with pytest.raises(RuntimeError):
        JsonlSink().write(frame)


def test_memory_sink_collects_frames(spec: VehicleSpec) -> None:
    session = make_session([ScriptStep(2.0)], spec, SimConfig())
    sink = MemorySink()
    session.attach_sink(sink)
    session.advance_seconds(2.0)
    session.close()

    assert len(sink.frames) == 20
    assert sink.closed is True
    assert sink.meta is not None


# --- Source -----------------------------------------------------------------


def test_simulator_source_produces_frames_headlessly(spec: VehicleSpec) -> None:
    config = SimConfig()
    source = SimulatorTelemetrySource(
        ScriptedInputProvider(DEMO_DRIVE, config), spec, config, duration_s=6.0
    )

    meta = source.start("trip-headless")
    frames = list(source.frames())
    source.stop()

    assert source.source_name == "simulator"
    assert meta.trip_id == "trip-headless"
    assert len(frames) == 60
    assert frames[0].trip_id == "trip-headless"
    assert all(frame.source == "simulator" for frame in frames)


def test_realtime_pacing_matches_wall_clock_duration(spec: VehicleSpec) -> None:
    config = SimConfig()
    source = SimulatorTelemetrySource(
        ScriptedInputProvider(DEMO_DRIVE, config), spec, config, duration_s=0.3
    )
    source.start("trip-realtime")
    start = time.perf_counter()
    frames = list(source.frames(realtime=True))
    elapsed = time.perf_counter() - start
    source.stop()

    assert len(frames) == 3
    # A bursty headless run produces 0.3s of telemetry in a few milliseconds;
    # realtime pacing must make it take close to 0.3s of actual wall time.
    assert elapsed >= 0.25


def test_default_pacing_runs_as_fast_as_the_cpu_allows(spec: VehicleSpec) -> None:
    config = SimConfig()
    source = SimulatorTelemetrySource(
        ScriptedInputProvider(DEMO_DRIVE, config), spec, config, duration_s=0.3
    )
    source.start("trip-fast")
    start = time.perf_counter()
    list(source.frames())
    elapsed = time.perf_counter() - start
    source.stop()

    assert elapsed < 0.1


def test_source_requires_start_before_use() -> None:
    source = SimulatorTelemetrySource(ScriptedInputProvider([ScriptStep(1.0)]))

    with pytest.raises(RuntimeError):
        list(source.frames())
