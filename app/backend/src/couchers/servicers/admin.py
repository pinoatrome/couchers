import json
import logging
from datetime import timedelta

import grpc
from shapely.geometry import shape
from sqlalchemy.sql import or_, select

from couchers import errors, urls
from couchers.db import session_scope
from couchers.helpers.clusters import create_cluster, create_node
from couchers.models import GroupChat, GroupChatSubscription, HostRequest, Message, User
from couchers.notifications.notify import notify
from couchers.servicers.auth import create_session
from couchers.servicers.communities import community_to_pb
from couchers.sql import couchers_select as select
from couchers.tasks import send_api_key_email
from couchers.utils import date_to_api, parse_date
from proto import admin_pb2, admin_pb2_grpc

logger = logging.getLogger(__name__)


def _user_to_details(user):
    return admin_pb2.UserDetails(
        user_id=user.id,
        username=user.username,
        email=user.email,
        gender=user.gender,
        birthdate=date_to_api(user.birthdate),
        banned=user.is_banned,
        deleted=user.is_deleted,
    )


class Admin(admin_pb2_grpc.AdminServicer):
    def GetUserDetails(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            return _user_to_details(user)

    def ChangeUserGender(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            user.gender = request.gender

            notify(
                user_id=user.id,
                topic="gender",
                key="",
                action="change",
                icon="wrench",
                title=f"An admin changed your gender",
                link=urls.account_settings_link(),
            )

            return _user_to_details(user)

    def ChangeUserBirthdate(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            user.birthdate = parse_date(request.birthdate)

            notify(
                user_id=user.id,
                topic="birthdate",
                key="",
                action="change",
                icon="wrench",
                title=f"An admin changed your birth date",
                link=urls.account_settings_link(),
            )

            return _user_to_details(user)

    def BanUser(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            user.is_banned = True
            return _user_to_details(user)

    def DeleteUser(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            user.is_deleted = True
            return _user_to_details(user)

    def CreateApiKey(self, request, context):
        with session_scope() as session:
            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)
            token, expiry = create_session(
                context, session, user, long_lived=True, is_api_key=True, duration=timedelta(days=365)
            )
            send_api_key_email(session, user, token, expiry)

            notify(
                user_id=user.id,
                topic="api_key",
                key="",
                action="create",
                icon="wrench",
                title=f"An admin created an API key for you, please check your email",
                link=urls.account_settings_link(),
            )

            return _user_to_details(user)

    def CreateCommunity(self, request, context):
        with session_scope() as session:
            geom = shape(json.loads(request.geojson))

            if geom.type != "MultiPolygon":
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, errors.NO_MULTIPOLYGON)

            parent_node_id = request.parent_node_id if request.parent_node_id != 0 else None
            node = create_node(session, geom, parent_node_id)
            create_cluster(
                session, node.id, request.name, request.description, context.user_id, request.admin_ids, True
            )

            return community_to_pb(node, context)

    def GetChats(self, request, context):
        with session_scope() as session:

            def format_user(user):
                return f"{user.name} ({user.username}, {user.id})"

            def format_conversation(conversation_id):
                out = ""
                with session_scope() as session:
                    messages = (
                        session.execute(
                            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc())
                        )
                        .scalars()
                        .all()
                    )
                    for message in messages:
                        out += f"Message {message.id} by {format_user(message.author)} at {message.time}\nType={message.message_type}, host_req_status_change={message.host_request_status_target}\n\n"
                        out += str(message.text)
                        out += "\n\n-----\n"
                    out += "\n\n\n\n"
                return out

            def format_host_request(host_request_id):
                out = ""
                with session_scope() as session:
                    host_request = session.execute(
                        select(HostRequest).where(HostRequest.conversation_id == host_request_id)
                    ).scalar_one()
                    out += "==============================\n"
                    out += f"Host request {host_request.conversation_id} from {format_user(host_request.surfer)} to {format_user(host_request.host)}.\nCurrent state = {host_request.status}\n\nMessages:\n"
                    out += format_conversation(host_request.conversation_id)
                    out += "\n\n\n\n"
                return out

            def format_group_chat(group_chat_id):
                out = ""
                with session_scope() as session:
                    group_chat = session.execute(
                        select(GroupChat).where(GroupChat.conversation_id == group_chat_id)
                    ).scalar_one()
                    out += "==============================\n"
                    out += f"Group chat {group_chat.conversation_id}. Created by {format_user(group_chat.creator)}, is_dm={group_chat.is_dm}\nName: {group_chat.title}\nMembers:\n"
                    subs = (
                        session.execute(
                            select(GroupChatSubscription)
                            .where(GroupChatSubscription.group_chat_id == group_chat.conversation_id)
                            .order_by(GroupChatSubscription.joined.asc())
                        )
                        .scalars()
                        .all()
                    )
                    for sub in subs:
                        out += f"{format_user(sub.user)} joined at {sub.joined} (left at {sub.left}), role={sub.role}\n"
                    out += "\n\nMessages:\n"
                    out += format_conversation(group_chat.conversation_id)
                    out += "\n\n\n\n"
                return out

            def format_all_chats_for_user(user_id):
                out = ""
                with session_scope() as session:
                    user = session.execute(select(User).where(User.id == user_id)).scalar_one()
                    out += f"Chats for user {format_user(user)}\n"
                    host_request_ids = (
                        session.execute(
                            select(HostRequest.conversation_id).where(
                                or_(HostRequest.host_user_id == user_id, HostRequest.surfer_user_id == user_id)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    out += f"************************************* Requests ({len(host_request_ids)})\n"
                    for host_request in host_request_ids:
                        out += format_host_request(host_request)
                    group_chat_ids = (
                        session.execute(
                            select(GroupChatSubscription.group_chat_id)
                            .where(GroupChatSubscription.user_id == user_id)
                            .order_by(GroupChatSubscription.joined.asc())
                        )
                        .scalars()
                        .all()
                    )
                    out += f"************************************* Group chats ({len(group_chat_ids)})\n"
                    for group_chat_id in group_chat_ids:
                        out += format_group_chat(group_chat_id)
                return out

            user = session.execute(select(User).where_username_or_email_or_id(request.user)).scalar_one_or_none()
            if not user:
                context.abort(grpc.StatusCode.NOT_FOUND, errors.USER_NOT_FOUND)

            return admin_pb2.GetChatsRes(response=format_all_chats_for_user(user.id))
