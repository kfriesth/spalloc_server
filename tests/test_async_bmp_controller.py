import pytest

from mock import Mock, call

import threading

from spinn_partition.async_bmp_controller import AsyncBMPController

from rig.links import Links


@pytest.yield_fixture
def abc():
    """Make an AsyncBMPController and stop it at the end."""
    abc = AsyncBMPController("localhost")
    yield abc
    abc.stop()
    abc.join()


@pytest.fixture
def bc(abc, monkeypatch):
    """Mock out the BMPController object."""
    bc = Mock()
    monkeypatch.setattr(abc, "_bc", bc)
    return bc


@pytest.mark.timeout(1.0)
def test_start_and_stop():
    # Make sure that if a BMP controller is started, we can stop it immediately
    abc = AsyncBMPController("localhost")
    assert abc._stop is False
    
    abc.stop()
    abc.join()
    assert abc._stop is True


@pytest.mark.timeout(1.0)
def test_set_power(abc, bc):
    # Make sure that the set power command works
    abc.set_power(10, False).wait()
    bc.set_power.assert_called_once_with(state=False, board=set([10]))
    bc.set_power.reset_mock()
    
    abc.set_power(11, True).wait()
    bc.set_power.assert_called_once_with(state=True, board=set([11]))
    bc.set_power.reset_mock()

@pytest.mark.timeout(1.0)
def test_set_power_fails(abc, bc):
    # Make sure that the set power command can fail and the done_event is still
    # fired.
    bc.set_power.side_effect = IOError()
    
    abc.set_power(10, False).wait()

@pytest.mark.timeout(1.0)
def test_set_power_blocks(abc, bc):
    # Make sure that the set power command can block
    event = threading.Event()
    bc.set_power.side_effect = (lambda *a, **k: event.wait())
    
    done_event = abc.set_power(10, False)
    
    # Block for a short time to ensure the background thread gets chance to
    # execute
    assert done_event.wait(0.1) is False
    
    # We should be sure the power command is blocking on the BMP call
    bc.set_power.assert_called_once_with(state=False, board=set([10]))
    
    # When the BMP call completes, so should the done_event!
    event.set()
    done_event.wait()

@pytest.mark.timeout(1.0)
def test_set_power_merge(abc, bc):
    # Make sure we can queue up several power commands which will get merged.
    events = []
    with abc._lock:
        events.append(abc.set_power(10, False))
        events.append(abc.set_power(11, False))
        events.append(abc.set_power(13, False))
    
    for event in events:
        event.wait()
    
    bc.set_power.assert_called_once_with(state=False, board=set([10, 11, 13]))

@pytest.mark.timeout(1.0)
def test_set_power_dont_merge(abc, bc):
    # Make sure power commands are only merged with those of the same type
    events = []
    with abc._lock:
        events.append(abc.set_power(10, False))
        events.append(abc.set_power(11, True))
        events.append(abc.set_power(12, False))
    
    for event in events:
        event.wait()
    
    assert bc.set_power.mock_calls == [
        call(state=False, board=set([10])),
        call(state=True, board=set([11])),
        call(state=False, board=set([12])),
    ]

@pytest.mark.timeout(1.0)
@pytest.mark.parametrize("enable,value", [(True, 0), (False, 1)])
@pytest.mark.parametrize("link,fpga,addr",
                         [(Links.east, 0, 0x0000005C),
                          (Links.south, 0, 0x0001005C),
                          (Links.south_west, 1, 0x0000005C),
                          (Links.west, 1, 0x0001005C),
                          (Links.north, 2, 0x0000005C),
                          (Links.north_east, 2, 0x0001005C)])
def test_set_link_enable(abc, bc, link, fpga, addr, enable, value):
    # Make sure that the set link command works
    abc.set_link_enable(10, link, enable).wait()
    bc.write_fpga_reg.assert_called_once_with(fpga, addr, value, board=10)
    bc.write_fpga_reg.reset_mock()

@pytest.mark.timeout(1.0)
def test_set_link_enable_fails(abc, bc):
    # Make sure that the set link command can fail and the done_event is still
    # fired.
    bc.write_fpga_reg.side_effect = IOError()
    
    abc.set_link_enable(10, Links.east, False).wait()

@pytest.mark.timeout(1.0)
def test_set_link_enable_blocks(abc, bc):
    # Make sure that the set power command can block
    event = threading.Event()
    bc.write_fpga_reg.side_effect = (lambda *a, **k: event.wait())
    
    done_event = abc.set_link_enable(10, Links.east, True)
    
    # Block for a short time to ensure the background thread gets chance to
    # execute
    assert done_event.wait(0.1) is False
    
    # We should be sure the power command is blocking on the BMP call
    bc.write_fpga_reg.assert_called_once_with(0, 0x5C, False, board=10)
    
    # When the BMP call completes, so should the done_event!
    event.set()
    done_event.wait()

@pytest.mark.timeout(1.0)
def test_power_priority(abc, bc):
    # Make sure that power queue has higher priority
    power_events = [threading.Event(), threading.Event()]
    link_event = threading.Event()
    bc.set_power.side_effect = (
        lambda e=power_events[:], *a, **k: e.pop().wait())
    bc.write_fpga_reg.side_effect = (lambda *a, **k: link_event.wait())
    
    with abc._lock:
        e1 = abc.set_power(10, True)
        e2 = abc.set_link_enable(11, Links.east, True)
        e3 = abc.set_power(12, False)
    
    # Block for a short time to ensure the background thread gets chance to
    # execute
    assert e1.wait(0.1) is False
    
    # Make sure just the power command has been called
    bc.set_power.assert_called_once_with(state=True, board=set([10]))
    bc.set_power.reset_mock()
    assert len(bc.write_fpga_reg.mock_calls) == 0
    
    # Let the first power command complete
    power_events.pop().set()
    e1.wait()
    
    # Block for a short time to ensure background thread gets chance to execute
    assert e3.wait(0.1) is False
    
    # Make sure just the power command has been called a second time (and not
    # the link setting command)
    bc.set_power.assert_called_once_with(state=False, board=set([12]))
    bc.set_power.reset_mock()
    assert len(bc.write_fpga_reg.mock_calls) == 0
    
    # Let the second power command complete
    power_events.pop().set()
    e3.wait()
    
    # Block for a short time to ensure background thread gets chance to execute
    assert e2.wait(0.1) is False
    
    # We should be sure the power command is blocking on the BMP call
    assert len(bc.set_power.mock_calls) == 0
    bc.write_fpga_reg.assert_called_once_with(0, 0x5C, False, board=11)
    
    # Make BMP call complete and the last event finish
    link_event.set()
    e2.wait()

@pytest.mark.timeout(1.0)
def test_stop_drains(abc, bc):
    # Make sure that the queues are emptied before the stop command is
    # processed
    with abc._lock:
        set_power_done = abc.set_power(10, False)
        set_link_enable_done = abc.set_link_enable(11, Links.east, False)
        abc.stop()

    # Both of these should be carried out
    set_power_done.wait()
    set_link_enable_done.wait()
    
    # And the loop should stop!
    abc.join()