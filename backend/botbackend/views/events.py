from flask import Blueprint, g, request, jsonify
from sqlalchemy.orm.exc import NoResultFound

from botbackend.model import Channel, Event, Server
from botbackend.model.validators import validate_push
from botbackend.model.types import EVENT_TYPES

blueprint = Blueprint("events", __name__)

def get_server_channel(server_id, channel_id=None, create=False):
    if not server_id:
        return None, None

    try:
        server = g.db.query(Server).filter(Server.server == server_id).one()
    except NoResultFound:
        server = None
        if create:
            server = Server(
                server=server_id
            )
            g.db.add(server)
            g.db.commit()

    if not channel_id:
        return server, None

    try:
        channel = g.db.query(Channel).filter(
            Channel.server == server.id
        ).filter(
            Channel.channel == channel_id
        ).one()
    except NoResultFound:
        channel = None
        if create:
            channel = Channel(
                server=server.id,
                channel=channel_id
            )
            g.db.add(channel)
            g.db.commit()

    return server, channel

def create_event(event_type, server, channel=None, data={}):
    event = Event(
        type=event_type,
        server=server.id,
        channel=channel.id if channel else None,
        data=data
    )
    g.db.add(event)
    g.db.commit()

@blueprint.route("/<type>", methods=["GET"])
def event_get(type=None):
    limit = request.args.get("limit", 5)
    try:
        limit = int(limit)
        if limit < 0 or limit > 200:
            raise ValueError()
    except (ValueError, TypeError):
        limit = 5

    before = request.args.get("before", None)
    try:
        before = int(before)
    except (ValueError, TypeError):
        before = None

    if type not in EVENT_TYPES:
        return jsonify({"state": "badtype"})

    query = g.db.query(Event).filter(Event.type == type)

    server, channel = get_server_channel(request.args.get("server"), request.args.get("channel"), create=False)
    if server:
        query = query.filter(Event.server == server.id)

    if channel:
        query = query.filter(Event.channel == channel.id)

    if before:
        query = query.filter(Event.id < before)

    return jsonify({
        "events": [_.to_dict() for _ in query.order_by(Event.posted.desc()).limit(limit).all()][::-1]
    })


@blueprint.route("/push", methods=["GET", "POST"])
def event_post():
    invalid = validate_push(request.json)
    if invalid:
        return jsonify({
            "status": "error",
            "error": invalid
        }), 503

    server, channel = get_server_channel(request.json["server"], request.json["channel"], create=True)
    create_event(request.json["type"], server, channel, request.json["data"])

    return jsonify({"status": "ok"})