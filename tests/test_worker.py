from concurrent import futures
from unittest.mock import ANY, patch

import pytest
from google.cloud.pubsub_v1.subscriber.scheduler import ThreadScheduler

from rele import Subscriber, Worker, sub
from rele.middleware import register_middleware
from rele.worker import create_and_run


@sub(topic="some-cool-topic", prefix="rele")
def sub_stub(data, **kwargs):
    print(f"I am a task doing stuff.")


@pytest.fixture
def worker(config):
    subscriptions = (sub_stub,)
    return Worker(
        subscriptions,
        config.gc_project_id,
        config.credentials,
        default_ack_deadline=60,
        threads_per_subscription=10,
    )


@pytest.fixture
def mock_consume():
    with patch.object(Subscriber, "consume") as m:
        yield m


@pytest.fixture
def mock_create_subscription():
    with patch.object(Subscriber, "create_subscription") as m:
        yield m


class TestWorker:
    def test_start_subscribes_and_saves_futures_when_subscriptions_given(
        self, mock_consume, worker
    ):
        worker.start()

        mock_consume.assert_called_once_with(
            subscription_name="rele-some-cool-topic",
            callback=ANY,
            scheduler=ANY,
        )
        scheduler = mock_consume.call_args_list[0][1]["scheduler"]
        assert isinstance(scheduler, ThreadScheduler)
        assert isinstance(scheduler._executor, futures.ThreadPoolExecutor)

    @patch.object(Worker, "_wait_forever")
    def test_run_sets_up_and_creates_subscriptions_when_called(
        self, mock_wait_forever, mock_consume, mock_create_subscription, worker
    ):
        worker.run_forever()

        mock_create_subscription.assert_called_once_with(sub_stub)
        mock_consume.assert_called_once_with(
            subscription_name="rele-some-cool-topic",
            callback=ANY,
            scheduler=ANY,
        )
        scheduler = mock_consume.call_args_list[0][1]["scheduler"]
        assert isinstance(scheduler, ThreadScheduler)
        assert isinstance(scheduler._executor, futures.ThreadPoolExecutor)
        mock_wait_forever.assert_called_once()

    @patch.object(Worker, "_wait_forever")
    @pytest.mark.usefixtures("mock_consume", "mock_create_subscription")
    def test_wait_forevers_for_custom_time_period_when_called_with_argument(
        self, mock_wait_forever, worker
    ):
        worker.run_forever(sleep_interval=127)

        mock_wait_forever.assert_called_once()

    @patch("rele.contrib.django_db_middleware.db.connections.close_all")
    def test_stop_closes_db_connections(self, mock_db_close_all, config, worker):
        config.middleware = ["rele.contrib.DjangoDBMiddleware"]
        register_middleware(config=config)

        with pytest.raises(SystemExit):
            worker.stop()

        mock_db_close_all.assert_called_once()

    @pytest.mark.usefixtures("mock_create_subscription")
    def test_creates_subscription_with_custom_ack_deadline_from_environment(
        self, config
    ):
        subscriptions = (sub_stub,)
        custom_ack_deadline = 234
        worker = Worker(
            subscriptions,
            config.gc_project_id,
            config.credentials,
            custom_ack_deadline,
            threads_per_subscription=10,
        )
        worker.setup()

        assert worker._subscriber._ack_deadline == custom_ack_deadline
        assert worker._subscriber._gc_project_id == "rele-test"


class TestCreateAndRun:
    @pytest.fixture(autouse=True)
    def worker_wait_forever(self):
        with patch.object(Worker, "_wait_forever", return_value=None) as p:
            yield p

    @pytest.fixture
    def mock_worker(self):
        with patch("rele.worker.Worker", autospec=True) as p:
            yield p

    def test_waits_forever_when_called_with_config_and_subs(self, config, mock_worker):
        subscriptions = (sub_stub,)
        create_and_run(subscriptions, config)

        mock_worker.assert_called_with(subscriptions, "rele-test", ANY, 60, 2)
        mock_worker.return_value.run_forever.assert_called_once_with()
