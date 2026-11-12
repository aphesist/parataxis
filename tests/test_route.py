"""contraprova's harness must run parataxis's lane layer, not its frozen copy."""

import sys

import parataxis.lanes
import parataxis.lanes_detect


def test_contraprova_lane_modules_are_parataxis_modules():
    import contraprova.harness as harness

    assert sys.modules["contraprova.harness.lanes"] is parataxis.lanes
    assert sys.modules["contraprova.harness.lanes_detect"] is parataxis.lanes_detect
    assert harness.lanes is parataxis.lanes


def test_swepro_run_binds_parataxis_lane_classes():
    from contraprova.harness import swepro_run

    assert swepro_run.LaneConfig is parataxis.lanes.LaneConfig
    assert swepro_run.lane_preflight is parataxis.lanes.lane_preflight


def test_lazy_import_in_the_pro_harness_resolves_to_parataxis():
    from contraprova.harness.lanes import run_la

    assert run_la is parataxis.lanes.run_la
