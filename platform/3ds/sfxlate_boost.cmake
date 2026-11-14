# sfxlate: selective loader/opener ceiling, boost alone. No message try-drain.
# Excluded from the glob above; active only for the pinned UNDERTALE audio ABI.
set(sfxlate_boost_default OFF)
if(CTRPORT_GAME STREQUAL "undertale" AND CTRPORT_TARGET STREQUAL "o3ds" AND NOT CTRPORT_AUDIO_METRICS AND NOT CTRPORT_AUDIO_PCM_HASH)
    set(sfxlate_boost_default ON)
endif()
option(CTRPORT_SFXLATE_AUDIOBOOST "Boost audio workers only across shared lock sections" ${sfxlate_boost_default})
if(CTRPORT_SFXLATE_AUDIOBOOST)
    if(NOT CTRPORT_GAME STREQUAL "undertale" OR NOT CTRPORT_TARGET STREQUAL "o3ds" OR CTRPORT_AUDIO_METRICS OR CTRPORT_AUDIO_PCM_HASH)
        message(FATAL_ERROR "sfxlate boost requires the pinned UNDERTALE Old audio layout without metrics/PCM hash")
    endif()
    target_sources(ctrport PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/source/z_audioboost.c")
    set(sfxlate_boost_offsets "CTRPORT_AUDIOBOOST_LOADLOCK_AT=19408" "CTRPORT_AUDIOBOOST_MSGLOCK_AT=15088"
        "CTRPORT_AUDIOBOOST_LOADER_AT=19420" "CTRPORT_AUDIOBOOST_OPENER_AT=15016"
        "CTRPORT_AUDIOBOOST_PRIORITY_AT=15012" "CTRPORT_AUDIOBOOST_STATE_AT=18188")
    set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_audio_system.c" APPEND PROPERTY COMPILE_DEFINITIONS
        "LightLock_Lock=CtrAudioBoost_lock" "LightLock_Unlock=CtrAudioBoost_unlock" CTRPORT_AUDIOBOOST
        ${sfxlate_boost_offsets})
    set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/main.c" APPEND PROPERTY COMPILE_DEFINITIONS
        "CtrAudioSystem_create=CtrAudioBoost_create")
    set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/source/z_audioboost.c" PROPERTIES
        COMPILE_DEFINITIONS "${sfxlate_boost_offsets}" COMPILE_OPTIONS "-Os")
    # Only the helper/string/calls differ. The release failure latch and fallback
    # use exactly the same code; NDEBUG cannot distinguish these build profiles.
    if(NOT CTRPORT_RELEASE_SOURCE_URL OR CTRPORT_SFXLATE_BOOST_TEST)
        set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/z_audioboost.c" APPEND PROPERTY
            COMPILE_DEFINITIONS CTRPORT_AUDIOBOOST_REPORT=1)
    endif()
endif()
