from bklms_downloader.onboarding import (
    ONBOARDING_STEPS,
    PANEL_HEIGHT,
    PANEL_WIDTH,
    OnboardingState,
    geometry_units_for_scaling,
    panel_position,
)


def test_onboarding_starts_at_first_step_and_honors_boundaries():
    state = OnboardingState()

    assert state.step_index == 0
    assert state.step == ONBOARDING_STEPS[0]
    assert state.is_first
    state.previous()
    assert state.step_index == 0

    for _ in range(len(ONBOARDING_STEPS) + 2):
        state.next()
    assert state.is_last
    assert state.step_index == len(ONBOARDING_STEPS) - 1


def test_manual_replay_uses_the_same_steps_without_resetting_persistence():
    state = OnboardingState(manual_replay=True)

    assert state.manual_replay
    assert state.total_steps == 6
    state.next()
    state.previous()
    assert state.step_index == 0


def test_all_steps_keep_the_same_fixed_panel_dimensions():
    state = OnboardingState()
    requested_sizes = []

    for _ in ONBOARDING_STEPS:
        requested_sizes.append((PANEL_WIDTH, PANEL_HEIGHT))
        state.next()

    assert requested_sizes == [(590, 370)] * len(ONBOARDING_STEPS)


def test_panel_position_is_centered_once_and_clamped_to_screen():
    assert panel_position(
        parent_x=200,
        parent_y=100,
        parent_width=1180,
        parent_height=790,
        screen_width=1920,
        screen_height=1080,
    ) == (495, 310)
    assert panel_position(
        parent_x=-800,
        parent_y=-400,
        parent_width=200,
        parent_height=100,
        screen_width=800,
        screen_height=600,
    ) == (16, 16)


def test_geometry_units_keep_the_requested_physical_panel_size_at_high_dpi():
    assert geometry_units_for_scaling(1.0) == (590, 370)
    assert geometry_units_for_scaling(1.25) == (472, 296)
    assert geometry_units_for_scaling(0) == (590, 370)
