"""Release tests must never discover the player's saves or removable cards."""
from pathlib import Path
import sys

import pytest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / 'builder'))
from gui_test_support import isolated_builder_host


@pytest.fixture(autouse=True)
def builder_host_safety(tmp_path, request):
    # Runs before unittest setUp too, so even an App constructed there is isolated.
    with isolated_builder_host(tmp_path / 'empty-builder-host') as root:
        # Ordinary page-navigation tests do not contact GitHub after Welcome.
        # The update protocol tests have their own poison-network guard and injected responses.
        if request.module.__name__.endswith('test_builder_updates'):
            yield root
        else:
            import updates
            with mock.patch.object(updates, 'fetch_latest', return_value=None):
                yield root
