# Assignment Policies & Workload Management

<cite>
**Referenced Files in This Document**
- [assignment_policy.rb](file://app/models/assignment_policy.rb)
- [inbox.rb](file://app/models/inbox.rb)
- [agent_assignment_service.rb](file://app/services/auto_assignment/agent_assignment_service.rb)
- [rate_limiter.rb](file://app/services/auto_assignment/rate_limiter.rb)
- [auto_assignment_handler.rb](file://app/models/concerns/auto_assignment_handler.rb)
- [assignment_service.rb](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb)
- [capacity_service.rb](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb)
- [constants.js](file://app/javascript/dashboard/routes/dashboard/settings/assignmentPolicy/constants.js)
- [fixtures.js](file://app/javascript/dashboard/store/modules/specs/assignmentPolicies/fixtures.js)
- [20250806140000_create_assignment_policies.rb](file://db/migrate/20250806140000_create_assignment_policies.rb)
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
This document explains Chatwoot’s assignment policies and workload management system, focusing on automatic conversation distribution, capacity controls, manual assignment workflows, and performance metrics. It covers:
- Automatic distribution algorithms: round-robin and balanced load (with policy-driven selection).
- Capacity management for agents, teams, and inbox-specific constraints.
- Manual assignment interfaces and reassignment flows.
- Metrics and monitoring for workload distribution and agent utilization.
- Configuration examples for different team structures and support models.
- Scalability considerations, real-time adjustments, and HR integration patterns.

## Project Structure
Assignment-related logic spans models, services, concerns, enterprise extensions, and frontend constants/fixtures. The key pieces are:
- Data model for assignment policies and their association to inboxes.
- Auto-assignment orchestration via services and handlers.
- Rate limiting and fair distribution windows.
- Enterprise features for balanced selection and capacity filtering.
- Frontend constants and fixtures that define policy options.

```mermaid
graph TB
subgraph "Data Model"
AP["AssignmentPolicy"]
INB["Inbox"]
end
subgraph "Auto-Assignment Core"
H["AutoAssignmentHandler"]
AAS["AgentAssignmentService"]
RL["RateLimiter"]
end
subgraph "Enterprise Extensions"
EAS["Enterprise::AutoAssignment::AssignmentService"]
ECS["Enterprise::AutoAssignment::CapacityService"]
end
subgraph "Frontend"
CJS["constants.js"]
FJS["fixtures.js"]
end
INB --> AP
H --> AAS
AAS --> RL
EAS --> ECS
CJS --> AP
FJS --> AP
```

**Diagram sources**
- [assignment_policy.rb:24-39](file://app/models/assignment_policy.rb#L24-L39)
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)
- [constants.js:1-20](file://app/javascript/dashboard/routes/dashboard/settings/assignmentPolicy/constants.js#L1-L20)
- [fixtures.js:1-57](file://app/javascript/dashboard/store/modules/specs/assignmentPolicies/fixtures.js#L1-L57)

**Section sources**
- [assignment_policy.rb:24-39](file://app/models/assignment_policy.rb#L24-L39)
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)
- [constants.js:1-20](file://app/javascript/dashboard/routes/dashboard/settings/assignmentPolicy/constants.js#L1-L20)
- [fixtures.js:1-57](file://app/javascript/dashboard/store/modules/specs/assignmentPolicies/fixtures.js#L1-L57)

## Core Components
- AssignmentPolicy: Defines distribution order, priority, fair distribution limits/windows, and age exclusions; linked to inboxes via a join table.
- Inbox: Holds auto-assignment settings and associates with an assignment policy.
- AutoAssignmentHandler: Triggers assignment on status transitions and enqueues jobs for redistribution.
- AgentAssignmentService: Performs round-robin selection among online, allowed agents under lock.
- RateLimiter: Enforces per-agent assignment rate using Redis with configurable limit/window from the policy.
- Enterprise AssignmentService: Extends base flow with balanced selector, capacity filtering, and exclusion rules.
- CapacityService: Checks agent capacity against inbox-specific limits.
- Frontend constants/fixtures: Define policy options and defaults for UI configuration.

**Section sources**
- [assignment_policy.rb:24-39](file://app/models/assignment_policy.rb#L24-L39)
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)
- [constants.js:1-20](file://app/javascript/dashboard/routes/dashboard/settings/assignmentPolicy/constants.js#L1-L20)
- [fixtures.js:1-57](file://app/javascript/dashboard/store/modules/specs/assignmentPolicies/fixtures.js#L1-L57)

## Architecture Overview
The assignment pipeline integrates model callbacks, background jobs, and service selectors:

```mermaid
sequenceDiagram
participant Conv as "Conversation"
participant Handler as "AutoAssignmentHandler"
participant Service as "AgentAssignmentService"
participant RR as "RoundRobinSelector"
participant RL as "RateLimiter"
participant EAS as "Enterprise : : AssignmentService"
participant ECS as "Enterprise : : CapacityService"
Conv->>Handler : Status changes (open/resolved/snoozed)
alt V2 enabled
Handler->>EAS : Enqueue assignment job
EAS->>ECS : Filter by capacity (if enabled)
EAS->>RR : Select agent (balanced or round-robin)
RR->>RL : Check rate limit
RL-->>RR : Within limit?
RR-->>EAS : Assignee
EAS-->>Conv : Set assignee
else Legacy path
Handler->>Service : assign_under_lock
Service->>RR : available_agent(allowed_online_agent_ids)
RR-->>Service : Assignee
Service-->>Conv : Set assignee
end
```

**Diagram sources**
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)

## Detailed Component Analysis

### Assignment Policy Model
- Purpose: Encapsulates distribution strategy and fairness parameters.
- Key fields:
  - assignment_order: round_robin (and balanced in enterprise).
  - conversation_priority: earliest_created or longest_waiting.
  - fair_distribution_limit: max assignments per window per agent.
  - fair_distribution_window: time window for rate limiting.
  - exclude_older_than_hours: threshold to skip stale unassigned conversations.
- Associations: Belongs to account; has many inboxes through inbox_assignment_policies.
- Validations: Presence/uniqueness of name; numeric constraints for limits/windows/exclusions.

```mermaid
classDiagram
class AssignmentPolicy {
+integer assignment_order
+integer conversation_priority
+integer fair_distribution_limit
+integer fair_distribution_window
+integer exclude_older_than_hours
+boolean enabled
+string name
+belongs_to : account
+has_many : inboxes
}
```

**Diagram sources**
- [assignment_policy.rb:24-39](file://app/models/assignment_policy.rb#L24-L39)
- [20250806140000_create_assignment_policies.rb:1-21](file://db/migrate/20250806140000_create_assignment_policies.rb#L1-L21)

**Section sources**
- [assignment_policy.rb:24-39](file://app/models/assignment_policy.rb#L24-L39)
- [20250806140000_create_assignment_policies.rb:1-21](file://db/migrate/20250806140000_create_assignment_policies.rb#L1-L21)

### Inbox Association and Settings
- Inboxes can be bound to an assignment policy via a one-to-one relationship.
- Inboxes expose assignable agents and member lists used during selection.

```mermaid
classDiagram
class Inbox {
+boolean enable_auto_assignment
+jsonb auto_assignment_config
+has_one : assignment_policy
}
Inbox --> AssignmentPolicy : "via inbox_assignment_policy"
```

**Diagram sources**
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)

**Section sources**
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)

### Automatic Distribution Algorithms

#### Round-Robin
- Selection is performed over online, allowed agents within the inbox.
- Uses a round-robin selector and respects rate limits per agent.

```mermaid
flowchart TD
Start(["Start"]) --> Online["Compute allowed online agent IDs"]
Online --> Select["Select next agent via round-robin"]
Select --> RateCheck{"Within rate limit?"}
RateCheck --> |No| Skip["Skip agent"]
Skip --> Select
RateCheck --> |Yes| Assign["Assign conversation"]
Assign --> End(["End"])
```

**Diagram sources**
- [agent_assignment_service.rb:61-76](file://app/services/auto_assignment/agent_assignment_service.rb#L61-L76)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)

**Section sources**
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)

#### Balanced Load (Enterprise)
- When advanced_assignment feature is enabled and policy indicates balanced mode, the enterprise balanced selector chooses agents considering capacity and fairness.
- Capacity filtering ensures agents do not exceed inbox-specific limits.

```mermaid
flowchart TD
Start(["Start"]) --> TeamFilter["Filter agents by team"]
TeamFilter --> RateFilter["Filter by rate limit"]
RateFilter --> CapFilter{"Capacity filtering enabled?"}
CapFilter --> |Yes| CapCheck["Filter by capacity (per inbox)"]
CapFilter --> |No| SelectorPick["Pick selector"]
CapCheck --> SelectorPick
SelectorPick --> Balanced{"Policy balanced AND feature enabled?"}
Balanced --> |Yes| BalancedSel["Use balanced selector"]
Balanced --> |No| RRSel["Use round-robin selector"]
BalancedSel --> Assign["Assign conversation"]
RRSel --> Assign
Assign --> End(["End"])
```

**Diagram sources**
- [assignment_service.rb:17-48](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L17-L48)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

**Section sources**
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

#### Skill-Based Routing
- Not present in the analyzed codebase. There is no explicit skill-based routing implementation visible in the referenced files.

[No sources needed since this section does not analyze specific files]

### Capacity Management

#### Individual Agent Limits
- Per-agent rate limiting uses Redis with a sliding window defined by fair_distribution_limit and fair_distribution_window from the assignment policy.

```mermaid
flowchart TD
Entry(["Track Assignment"]) --> Window["Compute window_start"]
Window --> Clean["Remove expired entries"]
Clean --> Add["Add current conversation id"]
Add --> Expire["Set TTL on key"]
Expire --> Exit(["Exit"])
```

**Diagram sources**
- [rate_limiter.rb:8-14](file://app/services/auto_assignment/rate_limiter.rb#L8-L14)
- [rate_limiter.rb:22-31](file://app/services/auto_assignment/rate_limiter.rb#L22-L31)

**Section sources**
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)

#### Team and Inbox-Specific Constraints
- Enterprise capacity service checks per-inbox conversation limits tied to an agent’s capacity policy. If no specific limit exists for an inbox, capacity is considered unlimited.

```mermaid
flowchart TD
Start(["Check Capacity"]) --> FindAccountUser["Find account_user for agent"]
FindAccountUser --> HasPolicy{"Has capacity policy?"}
HasPolicy --> |No| Unlimited["Unlimited capacity"]
HasPolicy --> |Yes| FindInboxLimit["Find inbox-specific limit"]
FindInboxLimit --> HasLimit{"Has inbox limit?"}
HasLimit --> |No| Unlimited
HasLimit --> |Yes| CountOpen["Count open conversations in inbox"]
CountOpen --> Compare{"Below limit?"}
Compare --> |Yes| Allow["Allow assignment"]
Compare --> |No| Deny["Deny assignment"]
```

**Diagram sources**
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

**Section sources**
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

### Manual Assignment Interfaces and Reassignment Workflows
- Manual assignment targets are validated to ensure they belong to the current account (assignee_id or team_id).
- Reassignment occurs when conversation status transitions trigger assignment logic, including resolved/snoozed states for redistribution.

```mermaid
sequenceDiagram
participant UI as "Dashboard UI"
participant API as "API Controller"
participant Concern as "ConversationAssignmentTargetsConcern"
participant Conv as "Conversation"
participant Handler as "AutoAssignmentHandler"
UI->>API : Update assignee/team
API->>Concern : validate_assignment_targets()
Concern-->>API : OK or error
API->>Conv : Save assignment change
Conv->>Handler : after_save triggers
Handler->>Handler : Decide if auto-assignment should run
```

**Diagram sources**
- [conversation_assignment_targets_concern.rb:1-13](file://app/controllers/concerns/conversation_assignment_targets_concern.rb#L1-L13)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)

**Section sources**
- [conversation_assignment_targets_concern.rb:1-13](file://app/controllers/concerns/conversation_assignment_targets_concern.rb#L1-L13)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)

### Override Capabilities
- Enterprise assignment service allows overriding base behavior with policy-driven configuration and selective selectors.
- Exclusion rules (labels and age) can prevent certain conversations from being auto-assigned.

```mermaid
flowchart TD
Start(["Override Flow"]) --> UsePolicy["Use policy config if present"]
UsePolicy --> ApplyExclusions["Apply label and age exclusions"]
ApplyExclusions --> Priority["Apply conversation priority ordering"]
Priority --> Select["Select agent via balanced or round-robin"]
Select --> End(["End"])
```

**Diagram sources**
- [assignment_service.rb:58-91](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L58-L91)

**Section sources**
- [assignment_service.rb:58-91](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L58-L91)

### Performance Metrics and Utilization Tracking
- Fair distribution window and limit provide a basis for measuring per-agent throughput and preventing overload.
- Conversation priority (earliest vs longest waiting) influences queue dynamics and SLA adherence.
- Age exclusions help avoid assigning stale conversations that could skew utilization metrics.

[No sources needed since this section provides general guidance]

### Configuration Examples
- Round-robin policy:
  - assignment_order: round_robin
  - conversation_priority: earliest_created
  - fair_distribution_limit: e.g., 100
  - fair_distribution_window: e.g., 3600 seconds
  - exclude_older_than_hours: e.g., 168 hours
- Balanced policy (enterprise):
  - assignment_order: balanced (when supported)
  - conversation_priority: longest_waiting
  - fair_distribution_limit/window: tuned for fairness
  - Enable advanced_assignment feature and configure agent capacity policies per inbox.

These values align with frontend constants and fixtures that define available options and defaults.

**Section sources**
- [constants.js:1-20](file://app/javascript/dashboard/routes/dashboard/settings/assignmentPolicy/constants.js#L1-L20)
- [fixtures.js:1-57](file://app/javascript/dashboard/store/modules/specs/assignmentPolicies/fixtures.js#L1-L57)

## Dependency Analysis
Key dependencies and relationships:
- Inbox depends on AssignmentPolicy via a join table.
- AutoAssignmentHandler orchestrates assignment triggers based on conversation state.
- AgentAssignmentService relies on round-robin selection and rate limiting.
- Enterprise AssignmentService extends base behavior with balanced selection and capacity filtering.
- CapacityService depends on account user mappings and inbox-specific limits.

```mermaid
graph LR
Inbox --> AssignmentPolicy
AutoAssignmentHandler --> AgentAssignmentService
AgentAssignmentService --> RateLimiter
EnterpriseAssignmentService --> CapacityService
EnterpriseAssignmentService --> AgentAssignmentService
```

**Diagram sources**
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

**Section sources**
- [inbox.rb:74-75](file://app/models/inbox.rb#L74-L75)
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [agent_assignment_service.rb:1-82](file://app/services/auto_assignment/agent_assignment_service.rb#L1-L82)
- [assignment_service.rb:1-93](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L1-L93)
- [capacity_service.rb:1-26](file://enterprise/app/services/enterprise/auto_assignment/capacity_service.rb#L1-L26)

## Performance Considerations
- Tune fair_distribution_limit and fair_distribution_window to match expected message volume and agent responsiveness.
- Use conversation_priority=longest_waiting to prioritize aging tickets and reduce bottlenecks.
- Enable capacity filtering to prevent hotspots on high-volume inboxes.
- Monitor Redis keys for assignment tracking and ensure proper TTL configuration.
- For large teams, prefer balanced selection with advanced_assignment enabled to distribute load more evenly.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Conversations not auto-assigned:
  - Verify inbox.auto_assignment_v2_enabled and handler conditions.
  - Ensure agents are online and members of the inbox.
  - Check rate limiter counts and policy limits.
- Overloaded agents:
  - Adjust fair_distribution_limit/window.
  - Enable capacity filtering and set inbox-specific limits.
- Stale conversations assigned unexpectedly:
  - Review exclude_older_than_hours and exclusion rules in capacity policy.

**Section sources**
- [auto_assignment_handler.rb:1-32](file://app/models/concerns/auto_assignment_handler.rb#L1-L32)
- [rate_limiter.rb:1-42](file://app/services/auto_assignment/rate_limiter.rb#L1-L42)
- [assignment_service.rb:58-91](file://enterprise/app/services/enterprise/auto_assignment/assignment_service.rb#L58-L91)

## Conclusion
Chatwoot’s assignment system combines robust data modeling, flexible policy configuration, and scalable service layers. Round-robin provides simple distribution, while enterprise features add balanced selection, capacity controls, and exclusion rules. Proper tuning of limits, windows, and priorities enables efficient workload distribution across teams and inboxes. For skill-based routing, additional customization would be required beyond the current codebase scope.

[No sources needed since this section summarizes without analyzing specific files]