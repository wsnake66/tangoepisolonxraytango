DEFAULT_BARRIER_MALE_TOP_EXTENSION = 0.1
INNER_CAVITY_BARRIER_MALE_TOP_EXTENSION = -5.0
INNER_CAVITY_MULTI_PART_BARRIER_MALE_TOP_EXTENSION = -8.0


def barrier_male_top_extension(scene) -> float:
    if bool(getattr(scene, "pro_inner_cavity", False)):
        core_type = str(
            getattr(scene, "pro_inner_cavity_core_type", "SINGLE_PART")
        )
        if core_type == "MULTI_PART":
            return INNER_CAVITY_MULTI_PART_BARRIER_MALE_TOP_EXTENSION
        return INNER_CAVITY_BARRIER_MALE_TOP_EXTENSION
    return DEFAULT_BARRIER_MALE_TOP_EXTENSION
