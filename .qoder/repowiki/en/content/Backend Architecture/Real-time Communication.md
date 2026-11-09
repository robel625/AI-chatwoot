# Real-time Communication

<cite>
**Referenced Files in This Document**
- [room_channel.rb](file://app/channels/room_channel.rb)
- [application_cable/channel.rb](file://app/channels/application_cable/channel.rb)
- [application_cable/connection.rb](file://app/channels/application_cable/connection.rb)
- [cable.yml](file://config/cable.yml)
- [actioncable.rb](file://config/initializers/actioncable.rb)
- [BaseActionCableConnector.js](file://app/javascript/shared/helpers/BaseActionCableConnector.js)
- [online_status_tracker.rb](file://lib/online_status_tracker.rb)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document explains Chatwoot’s real-time communication system built on ActionCable. It covers the WebSocket architecture for live conversation updates, agent notifications, and collaboration features; channel organization and connection management; message broadcasting patterns; client-side integration with reconnection handling; scaling considerations for high concurrency; room-based messaging; presence tracking; and real-time state synchronization.

## Project Structure
The real-time layer is implemented as:
- Server-side channels under app/channels
- Client-side WebSocket connector under app/javascript/shared/helpers
- Redis-backed pub/sub configuration under config/cable.yml and initializers
- Presence and availability logic under lib/online_status_tracker.rb

```mermaid
graph TB
subgraph "Client"
JS["BaseActionCableConnector.js"]
end
subgraph "Rails App"
AC["ActionCable Server"]
RC["RoomChannel"]
AChan["ApplicationCable::Channel"]
Conn["ApplicationCable::Connection"]
OST["OnlineStatusTracker"]
end
subgraph "Infrastructure"
Redis["Redis (Pub/Sub + Sorted Sets)"]
end
JS --> AC
AC --> RC
RC --> AChan
RC --> OST
AC --> Redis
OST --> Redis
```

**Diagram sources**
- [BaseActionCableConnector.js:1-48](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L48)
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)
- [application_cable/channel.rb:1-3](file://app/channels/application_cable/channel.rb#L1-L3)
- [application_cable/connection.rb:1-3](file://app/channels/application_cable/connection.rb#L1-L3)
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)
- [cable.yml:1-22](file://config/cable.yml#L1-L22)

**Section sources**
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)
- [application_cable/channel.rb:1-3](file://app/channels/application_cable/channel.rb#L1-L3)
- [application_cable/connection.rb:1-3](file://app/channels/application_cable/connection.rb#L1-L3)
- [cable.yml:1-22](file://config/cable.yml#L1-L22)
- [actioncable.rb:1-19](file://config/initializers/actioncable.rb#L1-L19)
- [BaseActionCableConnector.js:1-97](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L97)
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)

## Core Components
- RoomChannel: Handles subscription lifecycle, stream routing, presence updates, and broadcasts to clients.
- ApplicationCable::Channel: Base class for all channels.
- ApplicationCable::Connection: Base class for connections (extensible for auth).
- BaseActionCableConnector.js: Client-side consumer that subscribes to RoomChannel, manages presence pings, event dispatching, and reconnection.
- OnlineStatusTracker: Redis-backed presence and availability service used by channels and other services.
- ActionCable configuration: cable.yml and initializer for Redis adapter and connection behavior.

Key responsibilities:
- Connection and subscription setup
- Stream scoping per user and account
- Presence tracking and broadcast
- Event-driven updates via pub/sub tokens

**Section sources**
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)
- [application_cable/channel.rb:1-3](file://app/channels/application_cable/channel.rb#L1-L3)
- [application_cable/connection.rb:1-3](file://app/channels/application_cable/connection.rb#L1-L3)
- [BaseActionCableConnector.js:1-97](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L97)
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)
- [cable.yml:1-22](file://config/cable.yml#L1-L22)
- [actioncable.rb:1-19](file://config/initializers/actioncable.rb#L1-L19)

## Architecture Overview
The system uses ActionCable over WebSockets with Redis as the pub/sub backend. Clients connect to /cable, subscribe to RoomChannel with a pubsub_token and account/user identifiers. The server streams messages to scoped channels based on the token and account. Presence is maintained in Redis sorted sets and hashes, and periodically refreshed by client pings.

```mermaid
sequenceDiagram
participant Client as "Browser (BaseActionCableConnector.js)"
participant AC as "ActionCable Server"
participant RC as "RoomChannel"
participant OST as "OnlineStatusTracker"
participant Redis as "Redis"
Client->>AC : WebSocket connect (/cable)
Client->>AC : Subscribe to RoomChannel {pubsub_token, account_id, user_id}
AC->>RC : Initialize subscribed()
RC->>RC : ensure_stream(pubsub_token, account_*)
RC->>OST : update_presence(account_id, type, id)
OST->>Redis : zadd(presence_key, timestamp, id)
RC->>AC : broadcast(pubsub_token, {event : 'presence.update', data})
AC-->>Client : event 'presence.update'
Client->>AC : periodic update_presence()
Note over Client,Redis : Presence TTLs managed by OnlineStatusTracker
```

**Diagram sources**
- [BaseActionCableConnector.js:17-47](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L17-L47)
- [room_channel.rb:2-35](file://app/channels/room_channel.rb#L2-L35)
- [online_status_tracker.rb:10-18](file://lib/online_status_tracker.rb#L10-L18)
- [cable.yml:1-9](file://config/cable.yml#L1-L9)

## Detailed Component Analysis

### RoomChannel
Responsibilities:
- Authenticate context via params (pubsub_token, optional user_id)
- Resolve current_user and current_account
- Ensure streams for pubsub_token and account-scoped stream
- Update presence and broadcast presence updates

```mermaid
classDiagram
class RoomChannel {
+subscribed()
+update_presence()
-broadcast_presence()
-ensure_stream()
-update_subscription()
-pubsub_token()
-current_user()
-current_account()
}
class ApplicationCable_Channel {
}
class OnlineStatusTracker {
+update_presence(account_id, obj_type, obj_id)
+get_available_users(account_id)
+get_available_contacts(account_id)
}
RoomChannel --|> ApplicationCable_Channel : inherits
RoomChannel --> OnlineStatusTracker : uses
```

**Diagram sources**
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)
- [application_cable/channel.rb:1-3](file://app/channels/application_cable/channel.rb#L1-L3)
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)

**Section sources**
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)

### Client Connector (BaseActionCableConnector.js)
Responsibilities:
- Create ActionCable consumer and subscribe to RoomChannel
- Send periodic presence pings
- Handle received events via an event map
- Manage reconnection timers and callbacks

```mermaid
flowchart TD
Start(["Constructor"]) --> CreateConsumer["Create ActionCable consumer"]
CreateConsumer --> Subscribe["Subscribe to RoomChannel<br/>params: pubsub_token, account_id, user_id"]
Subscribe --> PresenceTimer["Start presence interval timer"]
PresenceTimer --> OnReceived["Handle received events"]
OnReceived --> Dispatch["Dispatch to registered event handlers"]
Subscribe --> Disconnected["On disconnect callback"]
Disconnected --> ReconnectTimer["Init reconnect timer"]
ReconnectTimer --> CheckConnection["Check connection status"]
CheckConnection --> |Reconnected| ClearTimer["Clear reconnect timer"]
CheckConnection --> |Still disconnected| ReconnectTimer
```

**Diagram sources**
- [BaseActionCableConnector.js:1-97](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L97)

**Section sources**
- [BaseActionCableConnector.js:1-97](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L97)

### Presence and Availability (OnlineStatusTracker)
Responsibilities:
- Maintain presence timestamps using Redis sorted sets
- Provide availability status via Redis hashes and fallback to DB
- Expose helpers to get available users and contacts within time windows

```mermaid
flowchart TD
U["update_presence(account_id, type, id)"] --> ZAdd["Redis zadd(presence_key, now, id)"]
G["get_available_users(account_id)"] --> ZRange["zrangeby score recent users"]
ZRange --> HMGet["hmget(status_key, user_ids)"]
HMGet --> Merge["Merge with DB availability if missing"]
GC["get_available_contacts(account_id)"] --> ZRem["zremrangebyscore stale records"]
ZRem --> ZRangeC["zrangeby score recent contacts"]
```

**Diagram sources**
- [online_status_tracker.rb:10-78](file://lib/online_status_tracker.rb#L10-L78)

**Section sources**
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)

### ActionCable Configuration
- Adapter: Redis with configurable URL, password, SSL verify mode, and channel prefix
- Reconnect attempts: exponential backoff list for Redis connection resilience
- Initializer: customizes Redis connector to support environments where certain commands are disabled and excludes reconnect_attempts from publisher config

```mermaid
graph LR
CableYML["cable.yml"] --> RedisAdapter["Redis Adapter"]
Init["actioncable.rb initializer"] --> RedisConnector["Custom Redis.new(config)"]
RedisAdapter --> PubSub["Pub/Sub Channels"]
RedisConnector --> Stability["Stability in restricted Redis envs"]
```

**Diagram sources**
- [cable.yml:1-22](file://config/cable.yml#L1-L22)
- [actioncable.rb:1-19](file://config/initializers/actioncable.rb#L1-L19)

**Section sources**
- [cable.yml:1-22](file://config/cable.yml#L1-L22)
- [actioncable.rb:1-19](file://config/initializers/actioncable.rb#L1-L19)

## Dependency Analysis
- RoomChannel depends on OnlineStatusTracker for presence and availability.
- BaseActionCableConnector.js depends on @rails/actioncable and subscribes to RoomChannel.
- ActionCable uses Redis as the transport for cross-process pub/sub.
- Presence data is stored in Redis sorted sets and hashes.

```mermaid
graph TB
RC["RoomChannel"] --> OST["OnlineStatusTracker"]
RC --> AC["ActionCable.server.broadcast"]
JS["BaseActionCableConnector.js"] --> AC
AC --> Redis["Redis"]
OST --> Redis
```

**Diagram sources**
- [room_channel.rb:19-35](file://app/channels/room_channel.rb#L19-L35)
- [BaseActionCableConnector.js:17-47](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L17-L47)
- [online_status_tracker.rb:10-78](file://lib/online_status_tracker.rb#L10-L78)
- [cable.yml:1-9](file://config/cable.yml#L1-L9)

**Section sources**
- [room_channel.rb:1-60](file://app/channels/room_channel.rb#L1-L60)
- [BaseActionCableConnector.js:1-97](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L1-L97)
- [online_status_tracker.rb:1-80](file://lib/online_status_tracker.rb#L1-L80)
- [cable.yml:1-22](file://config/cable.yml#L1-L22)

## Performance Considerations
- Use Redis-backed pub/sub for horizontal scaling across multiple Rails processes.
- Tune presence intervals:
  - Client presence ping interval balances freshness vs. overhead.
  - OnlineStatusTracker durations control how long presence remains valid without pings.
- Avoid heavy work inside channel callbacks; offload to background jobs when needed.
- Prefer streaming by pubsub_token and account-scoped streams to limit fan-out.
- Monitor Redis latency and memory usage; consider dedicated Redis instances for production.
- Configure reconnect_attempts in cable.yml to handle transient Redis outages gracefully.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- WebSocket connection failures:
  - Verify /cable endpoint is reachable and reverse proxy supports WebSockets.
  - Check Redis connectivity and credentials in cable.yml.
- Presence not updating:
  - Ensure client sends periodic update_presence calls.
  - Confirm OnlineStatusTracker presence keys are being written to Redis.
- High CPU or memory usage:
  - Reduce presence ping frequency.
  - Review large broadcasts; prefer targeted streams.
- Redis command restrictions:
  - If running in environments like Memorystore where certain commands are disabled, use the provided initializer to adjust Redis client configuration.

**Section sources**
- [cable.yml:1-22](file://config/cable.yml#L1-L22)
- [actioncable.rb:1-19](file://config/initializers/actioncable.rb#L1-L19)
- [BaseActionCableConnector.js:41-75](file://app/javascript/shared/helpers/BaseActionCableConnector.js#L41-L75)
- [online_status_tracker.rb:10-78](file://lib/online_status_tracker.rb#L10-L78)

## Conclusion
Chatwoot’s real-time layer leverages ActionCable with Redis for scalable, low-latency communication. RoomChannel coordinates subscription, streaming, and presence broadcasting, while the client connector ensures resilient connections and timely presence updates. OnlineStatusTracker centralizes presence and availability logic backed by Redis. With proper configuration and tuning, the system supports high-concurrency scenarios and robust real-time collaboration.

[No sources needed since this section summarizes without analyzing specific files]