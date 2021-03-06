import pytest

from mock import Mock, call

import threading

from spalloc_server.async_bmp_controller import AsyncBMPController

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


class OnDoneEvent(object):
    """An object which can be used as a dummy callback.

    The object is callable and expects to be called exactly once with a single
    argument: success or failure. This is recorded in the object's success
    attribute. Before the object is called this attribute is None.

    The object works like a :py:class:`threading.Event` which is set when the
    callback is called.
    """

    def __init__(self):
        self.event = threading.Event()
        self.success = None

    def set(self, *args, **kwargs):
        return self.event.set(*args, **kwargs)

    def wait(self, *args, **kwargs):
        return self.event.wait(*args, **kwargs)

    def __call__(self, success):
        # Should be passed a valid success value
        assert (success is True) or (success is False)

        # Should not have been called before
        assert self.success is None

        self.success = success

        self.set()


@pytest.mark.timeout(1.0)
@pytest.mark.parametrize("on_thread_start", [None, Mock()])
def test_start_and_stop(on_thread_start):
    # Make sure that if a BMP controller is started, we can stop it immediately
    abc = AsyncBMPController("localhost", on_thread_start=on_thread_start)
    assert abc._stop is False

    abc.stop()
    abc.join()
    assert abc._stop is True

    if on_thread_start is not None:
        on_thread_start.assert_called_once_with()


@pytest.mark.timeout(1.0)
@pytest.mark.parametrize("power_side_effect,success",
                         [(None, True),
                          (IOError("Fail."), False)])
def test_set_power(abc, bc, power_side_effect, success):
    # Make sure that the set power command works (and failure is reported)
    e = OnDoneEvent()
    bc.set_power.side_effect = power_side_effect
    abc.set_power(10, False, e)
    e.wait()
    assert e.success is success
    bc.set_power.assert_called_once_with(state=False, board=set([10]))
    bc.set_power.reset_mock()

    e = OnDoneEvent()
    abc.set_power(11, True, e)
    bc.set_power.side_effect = power_side_effect
    e.wait()
    assert e.success is success
    bc.set_power.assert_called_once_with(state=True, board=set([11]))
    bc.set_power.reset_mock()


@pytest.mark.timeout(1.0)
def test_set_power_blocks(abc, bc):
    # Make sure that the set power command can block
    event = threading.Event()
    bc.set_power.side_effect = (lambda *a, **k: event.wait())

    done_event = OnDoneEvent()
    abc.set_power(10, False, done_event)

    # Block for a short time to ensure the background thread gets chance to
    # execute
    assert done_event.wait(0.1) is False

    # We should be sure the power command is blocking on the BMP call
    bc.set_power.assert_called_once_with(state=False, board=set([10]))

    # When the BMP call completes, so should the done_event!
    event.set()
    done_event.wait()
    assert done_event.success is True


@pytest.mark.timeout(1.0)
@pytest.mark.parametrize("power_side_effect,success",
                         [(None, True),
                          (IOError("Fail."), False)])
def test_set_power_merge(abc, bc, power_side_effect, success):
    bc.set_power.side_effect = power_side_effect

    # Make sure we can queue up several power commands which will get merged
    # (and any errors duplicated).
    events = [OnDoneEvent() for _ in range(3)]
    with abc:
        abc.set_power(10, False, events[0])
        abc.set_power(11, False, events[1])
        abc.set_power(13, False, events[2])

    for event in events:
        event.wait()
        assert event.success is success

    bc.set_power.assert_called_once_with(state=False, board=set([10, 11, 13]))


@pytest.mark.timeout(1.0)
def test_set_power_dont_merge(abc, bc):
    # Make sure power commands are only merged with those of the same type
    events = [OnDoneEvent() for _ in range(3)]
    with abc:
        abc.set_power(10, False, events[0])
        abc.set_power(11, True, events[1])
        abc.set_power(12, False, events[2])

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
@pytest.mark.parametrize("side_effect,success",
                         [(None, True),
                          (IOError("Fail."), False)])
def test_set_link_enable(abc, bc, link, fpga, addr, enable, value,
                         side_effect, success):
    # Make sure that the set link command works (and failure is reported)
    e = OnDoneEvent()
    bc.write_fpga_reg.side_effect = side_effect
    abc.set_link_enable(10, link, enable, e)
    e.wait()
    assert e.success is success
    bc.write_fpga_reg.assert_called_once_with(fpga, addr, value, board=10)
    bc.write_fpga_reg.reset_mock()


@pytest.mark.timeout(1.0)
def test_set_link_enable_blocks(abc, bc):
    # Make sure that the set power command can block
    event = threading.Event()
    bc.write_fpga_reg.side_effect = (lambda *a, **k: event.wait())

    done_event = OnDoneEvent()
    abc.set_link_enable(10, Links.east, True, done_event)

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

    with abc:
        e1, e2, e3 = (OnDoneEvent() for _ in range(3))
        abc.set_power(10, True, e1)
        abc.set_link_enable(11, Links.east, True, e2)
        abc.set_power(12, False, e3)

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
def test_power_removes_link_enables(abc, bc):
    # Make sure link enable requests are removed for boards with newly added
    # power commands.
    with abc:
        e1, e2, e3, e4 = (OnDoneEvent() for _ in range(4))
        abc.set_power(10, True, e1)
        abc.set_link_enable(10, Links.east, True, e2)
        abc.set_link_enable(11, Links.east, True, e3)
        abc.set_power(11, False, e4)

    # Wait for the commands to complete
    e1.wait()
    e2.wait()
    e3.wait()
    e4.wait()

    # All commands should have finished (but the link enable on board 11 should
    # have failed)
    assert e1.success is True
    assert e2.success is True
    assert e3.success is False
    assert e4.success is True

    # Make sure both power commands were sent
    assert len(bc.set_power.mock_calls) == 2

    # But only one link command should be around
    bc.write_fpga_reg.assert_called_once_with(0, 0x5C, False, board=10)


@pytest.mark.timeout(1.0)
def test_stop_drains(abc, bc):
    # Make sure that the queues are emptied before the stop command is
    # processed
    set_power_done = OnDoneEvent()
    set_link_enable_done = OnDoneEvent()
    with abc:
        abc.set_power(10, False, set_power_done)
        abc.set_link_enable(11, Links.east, False, set_link_enable_done)
        abc.stop()

    # Both of these should be carried out
    set_power_done.wait()
    set_link_enable_done.wait()
    assert set_power_done.success is True
    assert set_link_enable_done.success is True

    # And the loop should stop!
    abc.join()
