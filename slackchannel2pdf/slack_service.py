from time import sleep

from babel.numbers import format_number, LC_NUMERIC
import slack

from .helpers import transform_encoding


class SlackService:
    """Service layer between main app and Slack API"""

    # limits for fetching messages from Slack
    _MESSAGES_PER_PAGE = 100  # max message retrieved per request during paging

    def __init__(self, slack_token) -> None:
        if slack_token is None:
            raise ValueError("slack_token can not be null")

        # load information for current Slack workspace
        self._client = slack.WebClient(token=slack_token)
        if slack_token != "TEST":
            self._workspace_info = self._fetch_workspace_info()
            self._user_names = self.fetch_user_names()
            self._channel_names = self._fetch_channel_names()
            self._usergroup_names = self._fetch_usergroup_names()
            self._is_test_mode = False

            # set author
            if "user_id" in self._workspace_info:
                author_id = self._workspace_info["user_id"]
                if self._workspace_info["user_id"] in self._user_names:
                    self._author = self._user_names[author_id]
                else:
                    self._author = "unknown_user_" + self._workspace_info["user_id"]
            else:
                author_id = None
                self._author = "unknown user"

        else:
            # if started with TEST parameter class properties will be
            # initialized empty and need to be set manually in test setup
            self._workspace_info = dict()
            self._user_names = dict()
            self._channel_names = dict()
            self._usergroup_names = dict()
            self._bot_names = dict()
            author_id = None
            self._author = "test user"
            self._is_test_mode = True

        if author_id is not None:
            self._author_info = self._fetch_user_info(author_id)
        else:
            self._author_info = dict()

    @property
    def author(self):
        return self._author

    @property
    def team(self):
        return self._workspace_info["team"]

    @property
    def is_test_mode(self):
        return self._is_test_mode

    def author_info(self) -> dict:
        return self._author_info

    def channel_names(self) -> dict:
        return self._channel_names

    def user_names(self) -> dict:
        return self._user_names

    def usergroup_names(self) -> dict:
        return self._usergroup_names

    def _fetch_workspace_info(self):
        """returns dict with info about current workspace"""

        print("Fetching workspace info from Slack...")
        res = self._client.auth_test()
        response = res.data
        assert response["ok"]
        return response

    def fetch_user_names(self):
        """returns dict of user names with user ID as key"""

        print("Fetching users for workspace...")
        response = self._client.users_list()
        assert response["ok"]
        user_names = self._reduce_to_dict(
            response["members"], "id", "real_name", "name"
        )
        for user in user_names:
            user_names[user] = transform_encoding(user_names[user])

        return user_names

    def _fetch_user_info(self, user_id):
        """returns dict of user info for user ID incl. locale"""

        print("Fetching user info for author...")
        response = self._client.users_info(user=user_id, include_locale=1)
        assert response["ok"]
        return response["user"]

    def _fetch_channel_names(self):
        """returns dict of channel names with channel ID as key"""

        print("Fetching channels for workspace...")
        response = self._client.conversations_list(
            types="public_channel,private_channel"
        )
        assert response["ok"]
        channel_names = self._reduce_to_dict(response["channels"], "id", "name")
        for channel in channel_names:
            channel_names[channel] = transform_encoding(channel_names[channel])

        return channel_names

    def _fetch_usergroup_names(self):
        """returns dict of usergroup names with usergroup ID as key"""

        print("Fetching usergroups for workspace...")
        response = self._client.usergroups_list()
        assert response["ok"]
        usergroup_names = self._reduce_to_dict(response["usergroups"], "id", "handle")
        for usergroup in usergroup_names:
            usergroup_names[usergroup] = transform_encoding(usergroup_names[usergroup])

        return usergroup_names

    def fetch_messages_from_channel(
        self, channel_id, max_messages, locale=LC_NUMERIC, oldest=None, latest=None
    ):
        """retrieve messages from a channel on Slack and return as list"""

        messages_per_page = min(self._MESSAGES_PER_PAGE, max_messages)
        oldest_ts = str(oldest.timestamp()) if oldest is not None else 0
        latest_ts = str(latest.timestamp()) if latest is not None else 0
        messages = self._fetch_pages(
            "conversations_history",
            args={
                "channel": channel_id,
                "oldest": oldest_ts,
                "latest": latest_ts,
            },
            limit=messages_per_page,
            key="messages",
            max_rows=max_messages,
        )
        print(
            f"Fetched a total of "
            f"{format_number(len(messages), locale=locale)}"
            f" messages from channel {self._channel_names[channel_id]}"
        )
        return messages

    def _fetch_pages(
        self, method, args: dict, limit: int, key: str, max_rows: int
    ) -> list:
        # get first page
        page = 1
        print(f"{method} - Fetching page {page}")
        new_args = {**args, **{"limit": limit}}
        response = getattr(self._client, method)(**new_args)
        assert response["ok"]
        rows = response[key]

        # get additional pages if below max message and if they are any
        while len(rows) < max_rows and response.get("response_metadata"):
            page += 1
            print(f"{method} - Fetching page {page}")
            sleep(1)  # need to wait 1 sec before next call due to rate limits
            # allow smaller page sized to fetch final page
            page_limit = min(limit, max_rows - len(rows))
            new_args = {
                **args,
                **{
                    "limit": page_limit,
                    "cursor": response["response_metadata"].get("next_cursor"),
                },
            }
            response = getattr(self._client, method)(**new_args)
            assert response["ok"]
            rows += response[key]

        return rows

    def fetch_threads_from_messages(
        self,
        channel_id,
        messages,
        max_messages,
        locale=LC_NUMERIC,
        oldest=None,
        latest=None,
    ) -> dict:
        """returns threads from all messages from for a channel as dict"""

        threads = dict()
        thread_num = 0
        thread_messages_total = 0
        for msg in messages:
            if "thread_ts" in msg and msg["thread_ts"] == msg["ts"]:
                thread_ts = msg["thread_ts"]
                thread_num += 1
                thread_messages = self._fetch_messages_from_thread(
                    channel_id, thread_ts, thread_num, max_messages, oldest, latest
                )
                threads[thread_ts] = thread_messages
                thread_messages_total += len(thread_messages)

        if thread_messages_total > 0:
            print(
                f"Fetched a total of "
                f"{format_number(thread_messages_total, locale=locale)}"
                f" messages from {thread_num} threads"
            )
        else:
            print("This channel has no threads")

        return threads

    def _fetch_messages_from_thread(
        self, channel_id, thread_ts, thread_num, max_messages, oldest=None, latest=None
    ) -> list:
        """retrieve messages from a Slack thread and return as list"""
        messages_per_page = min(self._MESSAGES_PER_PAGE, max_messages)
        oldest_ts = str(oldest.timestamp()) if oldest is not None else 0
        latest_ts = str(latest.timestamp()) if latest is not None else 0
        messages = self._fetch_pages(
            "conversations_replies",
            args={
                "channel": channel_id,
                "ts": thread_ts,
                "oldest": oldest_ts,
                "latest": latest_ts,
            },
            limit=messages_per_page,
            key="messages",
            max_rows=max_messages,
        )
        return messages

    # def _fetch_messages_from_thread_old(
    #     self, channel_id, thread_ts, thread_num, max_messages, oldest=None, latest=None
    # ):
    #     """retrieve messages from a Slack thread and return as list"""

    #     messages_per_page = min(self._MESSAGES_PER_PAGE, max_messages)
    #     # get first page
    #     page = 1
    #     print(f"Fetching messages from thread {thread_num} - page {page}")
    #     oldest_ts = str(oldest.timestamp()) if oldest is not None else 0
    #     latest_ts = str(latest.timestamp()) if latest is not None else 0
    #     response = self._client.conversations_replies(
    #         channel=channel_id,
    #         ts=thread_ts,
    #         limit=messages_per_page,
    #         oldest=oldest_ts,
    #         latest=latest_ts,
    #     )
    #     assert response["ok"]
    #     messages_all = response["messages"]

    #     # get additional pages if below max message and if they are any
    #     while (
    #         len(messages_all) + messages_per_page <= max_messages
    #         and response["has_more"]
    #     ):
    #         page += 1
    #         print(f"Fetching messages from thread {thread_num} - page {page}")
    #         sleep(1)  # need to wait 1 sec before next call due to rate limits
    #         response = self._client.conversations_replies(
    #             channel=channel_id,
    #             ts=thread_ts,
    #             limit=messages_per_page,
    #             oldest=oldest_ts,
    #             latest=latest_ts,
    #             cursor=response["response_metadata"]["next_cursor"],
    #         )
    #         assert response["ok"]
    #         messages = response["messages"]
    #         messages_all = messages_all + messages

    #     return messages_all

    def fetch_bot_names_for_messages(self, messages, threads):
        """Fetches bot names from API for provided messages

        Will only fetch names for bots that never appeared with a username
        in any message (lazy approach since calls to bots_info are very slow)
        """

        # collect bot_ids without user name from messages
        bot_ids = list()
        bot_names = dict()
        for msg in messages:
            if "bot_id" in msg:
                bot_id = msg["bot_id"]
                if "username" in msg:
                    bot_names[bot_id] = transform_encoding(msg["username"])
                else:
                    bot_ids.append(bot_id)

        # collect bot_ids without user name from thread messages
        for thread_messages in threads:
            for msg in thread_messages:
                if "bot_id" in msg:
                    bot_id = msg["bot_id"]
                    if "username" in msg:
                        bot_names[bot_id] = transform_encoding(msg["username"])
                    else:
                        bot_ids.append(bot_id)

        # Find bot IDs that are not in bot_names
        bot_ids = set(bot_ids).difference(bot_names.keys())

        # collect bot names from API if needed
        if len(bot_ids) > 0:
            print(f"Fetching names for {len(bot_ids)} bots")
            for bot_id in bot_ids:
                response = self._client.bots_info(bot=bot_id)
                if response["ok"]:
                    bot_names[bot_id] = self._transform_encoding(
                        response["bot"]["name"]
                    )
                    sleep(1)  # need to wait 1 sec before next call due to rate limits

        return bot_names

    @staticmethod
    def _reduce_to_dict(arr, key_name, col_name_primary, col_name_secondary=None):
        """returns dict with selected columns as key and value from list of dict

        Args:
            arr: list of dicts to reduce
            key_name: name of column to become key
            col_name_primary: colum will become value if it exists
            col_name_secondary: colum will become value if col_name_primary
                does not exist and this argument is provided

        dict items with no matching key_name, col_name_primary and
        col_name_secondary will not be included in the resulting new dict

        """
        arr2 = dict()
        for item in arr:
            if key_name in item:
                key = item[key_name]
                if col_name_primary in item:
                    arr2[key] = item[col_name_primary]
                elif col_name_secondary is not None and col_name_secondary in item:
                    arr2[key] = item[col_name_secondary]
        return arr2
