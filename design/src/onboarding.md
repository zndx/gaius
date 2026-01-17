# Onboarding

> **Status**: Design Draft
> **Last Updated**: 2026-01-17

---

## Overview

Gaius onboarding provides a guided, agent-assisted setup experience that:
1. Configures the development environment (devenv + nixpkgs)
2. Connects external inference APIs and integrations
3. Personalizes the experience via domain-specific Onboarding Agents
4. Maintains CLI/MCP/TUI parity for all onboarding commands

```mermaid
flowchart TB
    subgraph User["New User"]
        Profile[User Profile<br/>work, home, side-project]
        Domain[Target Domain<br/>manufacturing, research, ops]
    end

    subgraph Onboarding["Onboarding Flow"]
        Command["#47;onboarding<br/>--profile --domain"]
        Agent[Onboarding Agent<br/>via ACP]
        DevEnv[DevEnv Setup<br/>nixpkgs]
        Integrations[External Integrations<br/>APIs, credentials]
    end

    subgraph AgentSources["Agent Sources"]
        Public[Public Repos<br/>github.com/...]
        Private[Private Repos<br/>gitlab.enterprise.com/...]
        Subscription[Subscription Repos<br/>Licensed agents]
    end

    User --> Command
    Command --> Agent
    AgentSources --> |"HOCON config"| Agent
    Agent --> DevEnv
    Agent --> Integrations
```

---

## Development Environment

### Devenv + Nixpkgs

Gaius uses [devenv](https://devenv.sh/) with nixpkgs for reproducible development environments.

```bash
# Initial setup
curl -fsSL https://install.determinate.systems/nix | sh
nix-env -iA devenv -f https://github.com/NixOS/nixpkgs/tarball/nixpkgs-unstable

# Enter development shell
cd gaius
devenv up
```

#### What devenv provides:

| Component | Purpose |
|-----------|---------|
| Python 3.11+ | Runtime with uv for package management |
| PostgreSQL | Metadata storage, state tracking |
| MinIO | S3-compatible object storage for KB |
| Qdrant | Vector database for embeddings |
| Aeron | Low-latency agent IPC (in progress) |
| Process Compose | Service orchestration |

#### Environment Profiles

```nix
# devenv.nix profiles
{
  profiles = {
    minimal = {
      # Core services only
      services.postgres.enable = true;
      services.minio.enable = true;
    };

    full = {
      # All services including GPU inference
      imports = [ ./profiles/minimal.nix ];
      services.qdrant.enable = true;
      services.vllm.enable = true;
    };

    ci = {
      # CI/CD optimized
      imports = [ ./profiles/minimal.nix ];
      processes.test-runner.enable = true;
    };
  };
}
```

---

## Onboarding Agent

### ACP Integration

The Onboarding Agent runs via [Agent Communication Protocol (ACP)](https://agentcommunicationprotocol.dev/), maintaining parity with other Gaius agents.

```mermaid
sequenceDiagram
    participant User
    participant CLI as gaius-cli
    participant MCP as MCP Server
    participant ACP as ACP Runtime
    participant Agent as Onboarding Agent

    User->>CLI: /onboarding --profile engineer --domain manufacturing
    CLI->>MCP: onboarding.start(profile, domain)
    MCP->>ACP: spawn_agent(onboarding, config)
    ACP->>Agent: Initialize with context

    loop Interactive Setup
        Agent->>User: Prompt for configuration
        User->>Agent: Provide input
        Agent->>Agent: Validate & configure
    end

    Agent->>ACP: Setup complete
    ACP->>MCP: Result summary
    MCP->>CLI: Display completion
```

### Command Interface

```bash
# CLI
gaius-cli --cmd "/onboarding --profile engineer --domain manufacturing"

# TUI (interactive)
/onboarding --profile engineer --domain manufacturing

# MCP (programmatic)
{
  "method": "tools/call",
  "params": {
    "name": "onboarding",
    "arguments": {
      "profile": "engineer",
      "domain": "manufacturing"
    }
  }
}
```

### Profiles

Profiles represent the user's current *perspective* or *context*—not their role. A single user may switch between profiles throughout the day.

| Profile | Description | Default Integrations |
|---------|-------------|---------------------|
| `work` | Professional/employer context | Corporate SSO, internal KBs, compliance-aware |
| `home` | Personal projects and learning | Personal GitHub, local storage, relaxed policies |
| `side-project` | Independent ventures | Separate credentials, isolated KBs |
| `research` | Academic/exploration mode | arXiv, Semantic Scholar, citation tracking |
| `consulting` | Client-facing work | Per-client credentials, data isolation |

Profiles isolate:
- **Credentials**: Different API keys, OAuth tokens per context
- **Knowledge bases**: Separate KB roots and sync targets
- **Inference routing**: Work may use enterprise endpoints; home uses personal quotas
- **Privacy boundaries**: Prevent cross-contamination between contexts

### The Profile × Domain Matrix

Gaius supports a rich way of relating to the global information landscape. A single domain takes on entirely different meaning depending on the user's current profile.

**Example: `--domain weather`**

| Profile | Context | Weather Domain Manifests As... |
|---------|---------|-------------------------------|
| `work` | Meteorologist | NWP models, GRIB data, forecast verification, research papers |
| `home` | Greenhouse builder | Microclimate data, frost dates, solar angles, irrigation planning |
| `family` | Vacation planner | 10-day forecasts, historical averages, best-time-to-visit guides |
| `leisure` | Storm chaser | Convective outlooks, radar composites, supercell dynamics |
| `leisure` | Photographer | Golden hour times, cloud formations, dramatic light conditions |
| `leisure` | Surfer | Swell models, wind forecasts, tide charts, wave period data |

The same person, the same domain, six completely different relationships to information. Gaius embraces this multiplicity—your professional expertise, personal projects, family life, and hobbies each deserve their own context, their own KB trajectory, their own way of seeing.

```mermaid
flowchart LR
    subgraph Profiles["User Profiles"]
        Work[work]
        Home[home]
        Family[family]
        Leisure[leisure]
    end

    subgraph Domain["Domain: Weather"]
        Weather((weather))
    end

    subgraph Realizations["Different Realizations"]
        R1[NWP Models<br/>Research Papers]
        R2[Microclimate<br/>Frost Dates]
        R3[Vacation Forecasts<br/>Travel Guides]
        R4[Storm Chasing<br/>Surf Reports<br/>Golden Hour]
    end

    Work --> Weather
    Home --> Weather
    Family --> Weather
    Leisure --> Weather

    Weather --> R1
    Weather --> R2
    Weather --> R3
    Weather --> R4
```

This is not just about filtering—it's about *framing*. The agent swarm navigates the KB differently, surfaces different connections, speaks in different registers, all based on who you are *right now*.

### Domains

| Domain | KB Sources | Specialized Agents |
|--------|------------|-------------------|
| `manufacturing` | Process docs, equipment manuals, quality specs | FDMM agents |
| `research` | Papers, patents, technical reports | Literature review agents |
| `operations` | Runbooks, incident reports, SLAs | SRE agents |
| `finance` | Reports, regulations, market data | Compliance agents |
| `custom` | User-specified sources | User-provided agents |

---

## Remote Agent Repositories

### Configuration

Onboarding Agents are loaded from remote git repositories specified in HOCON configuration:

```hocon
# ~/.config/gaius/agents.conf

agents {
  repositories = [
    # Public GitHub repo
    {
      url = "https://github.com/gaius-project/onboarding-agents"
      branch = "main"
      auth = "none"
    }

    # Private GitHub repo (PAT auth)
    {
      url = "https://github.com/acme-corp/gaius-agents"
      branch = "release"
      auth = "github-pat"
      credentials = ${GITHUB_PAT}
    }

    # GitLab enterprise (OAuth)
    {
      url = "https://gitlab.enterprise.com/ai-team/onboarding"
      branch = "stable"
      auth = "gitlab-oauth"
      credentials = ${GITLAB_TOKEN}
    }

    # Subscription-based (API key)
    {
      url = "https://agents.gaius.dev/premium/manufacturing"
      branch = "v2"
      auth = "api-key"
      credentials = ${GAIUS_SUBSCRIPTION_KEY}
      license = "enterprise"
    }
  ]

  # Resolution order (first match wins)
  resolution = "priority"  # or "merge", "override"

  # Cache settings
  cache {
    enabled = true
    ttl = "24h"
    path = ${HOME}/.cache/gaius/agents
  }
}
```

### Repository Structure

```
onboarding-agents/
├── manifest.yaml           # Agent catalog
├── agents/
│   ├── engineer/
│   │   ├── agent.yaml      # Agent definition
│   │   ├── prompts/        # System prompts
│   │   ├── tools/          # Custom tools
│   │   └── workflows/      # Multi-step flows
│   ├── researcher/
│   └── manufacturing/
├── integrations/
│   ├── cerebras.yaml
│   ├── grok.yaml
│   └── bytez.yaml
└── domains/
    ├── manufacturing/
    └── research/
```

### Manifest Format

```yaml
# manifest.yaml
name: gaius-onboarding-agents
version: 2.1.0
license: Apache-2.0  # or "proprietary", "subscription"

agents:
  - id: onboarding-engineer
    name: Engineer Onboarding
    profile: engineer
    domains: [software, infrastructure]
    min_gaius_version: "0.9.0"

  - id: onboarding-manufacturing
    name: Manufacturing Onboarding
    profile: operator
    domains: [manufacturing]
    requires:
      - fdmm-kb
      - equipment-api

integrations:
  - id: cerebras-inference
    type: inference
    provider: cerebras

subscription:
  required: false
  tier: community  # or "professional", "enterprise"
```

### Authentication Methods

| Method | Use Case | Configuration |
|--------|----------|---------------|
| `none` | Public repos | No credentials needed |
| `github-pat` | Private GitHub | Personal Access Token |
| `github-app` | Org GitHub | GitHub App installation |
| `gitlab-oauth` | GitLab repos | OAuth token |
| `ssh` | Any git host | SSH key |
| `api-key` | Subscription services | Vendor API key |

---

## External Integrations

### Inference APIs

#### Cerebras

Ultra-fast inference for interactive use cases.

```hocon
# integrations.conf
inference.cerebras {
  enabled = true
  api_key = ${CEREBRAS_API_KEY}
  model = "llama-3.3-70b"

  # Use for fast responses
  routing {
    latency_sensitive = true
    max_tokens = 4096
  }
}
```

```python
# Usage in agent
from gaius.providers.cerebras import CerebrasClient

client = CerebrasClient()
response = await client.complete(
    prompt="Explain the FDMM capability model",
    model="llama-3.3-70b"
)
```

#### xAI Grok

Advanced reasoning with real-time data access.

```hocon
inference.grok {
  enabled = true
  api_key = ${XAI_API_KEY}

  models {
    text = "grok-2"
    voice = "grok-voice"  # For voice agents
  }

  features {
    web_search = true      # Real-time X data
    tool_calling = true
    voice_agent = true     # WebRTC voice
  }
}
```

#### Bytez

Cost-effective batch processing.

```hocon
inference.bytez {
  enabled = true
  api_key = ${BYTEZ_API_KEY}

  # Use for background tasks
  routing {
    batch_processing = true
    cost_optimized = true
  }
}
```

### FMP API (Financial Modeling Prep)

Financial data integration for business domains.

```hocon
integrations.fmp {
  enabled = true
  api_key = ${FMP_API_KEY}

  endpoints {
    company_profile = true
    financial_statements = true
    stock_quotes = true
    sec_filings = true
  }

  cache {
    enabled = true
    ttl = "1h"
  }
}
```

```python
# Usage
from gaius.integrations.fmp import FMPClient

fmp = FMPClient()
profile = await fmp.company_profile("AAPL")
financials = await fmp.income_statement("AAPL", period="annual", limit=5)
```

### Mistral-Vibe ACP Agent

Multimodal agent for visual understanding tasks.

```hocon
agents.mistral_vibe {
  enabled = true
  acp_endpoint = "https://acp.mistral.ai/v1"
  api_key = ${MISTRAL_API_KEY}

  capabilities {
    image_understanding = true
    document_analysis = true
    chart_interpretation = true
  }

  # Integration with Gaius
  routing {
    visual_queries = true
    document_qa = true
  }
}
```

```mermaid
flowchart LR
    subgraph Gaius["Gaius Agent"]
        Query[User Query]
        Router[Task Router]
    end

    subgraph MistralVibe["Mistral-Vibe ACP"]
        Vision[Vision Model]
        Analysis[Document Analysis]
    end

    subgraph Output["Results"]
        Text[Text Response]
        Structured[Structured Data]
    end

    Query --> Router
    Router --> |"Visual task"| Vision
    Router --> |"Document task"| Analysis
    Vision --> Text
    Analysis --> Structured
```

---

## Onboarding Flow

### Step-by-Step Process

```mermaid
stateDiagram-v2
    [*] --> Welcome

    Welcome --> ProfileSelection: Start onboarding
    ProfileSelection --> DomainSelection: Select profile

    DomainSelection --> DevEnvSetup: Select domain
    DevEnvSetup --> IntegrationSetup: Configure devenv

    IntegrationSetup --> AgentDownload: Add API keys
    AgentDownload --> KBInitialization: Fetch agents from repos

    KBInitialization --> Verification: Sync knowledge bases
    Verification --> Complete: Run health checks

    Complete --> [*]: Ready to use

    state DevEnvSetup {
        [*] --> CheckNix
        CheckNix --> InstallNix: Not installed
        CheckNix --> ConfigureDevenv: Installed
        InstallNix --> ConfigureDevenv
        ConfigureDevenv --> StartServices
        StartServices --> [*]
    }

    state IntegrationSetup {
        [*] --> ListIntegrations
        ListIntegrations --> ConfigureAPI: For each
        ConfigureAPI --> ValidateAPI
        ValidateAPI --> ListIntegrations: More
        ValidateAPI --> [*]: Done
    }
```

### Interactive Prompts

The Onboarding Agent guides users through perspective-based setup. The flow is designed to translate directly to BDD specifications.

#### Feature: Profile Creation

```gherkin
Feature: User profile creation
  As a new Gaius user
  I want to create a profile representing my current perspective
  So that Gaius can frame information appropriately for my context

  Background:
    Given the onboarding agent is initialized
    And no profiles exist for this user

  Scenario: Create first profile with common perspective
    When the user starts onboarding
    Then the agent should ask "What perspective are you working from right now?"
    And present options including:
      | Option       | Description                                      |
      | work         | Professional context with employer resources     |
      | home         | Personal projects and learning                   |
      | side-project | Independent ventures, isolated from work         |
      | research     | Academic exploration and study                   |
      | leisure      | Hobbies, interests, and personal enrichment      |

  Scenario: Create custom perspective
    Given the user selects "other"
    When the user enters "consulting-acme"
    Then a new profile "consulting-acme" should be created
    And the agent should ask about credential isolation preferences

  Scenario: User has existing profiles
    Given the user has profiles ["work", "home"]
    When the user starts onboarding for a new profile
    Then the agent should offer to clone settings from existing profiles
    And highlight what will be isolated vs shared
```

```
┌─────────────────────────────────────────────────────────────┐
│  Welcome to Gaius                                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  What perspective are you working from right now?           │
│                                                             │
│  This isn't about your job title—it's about your current    │
│  context. You can have many profiles and switch between     │
│  them freely.                                               │
│                                                             │
│  > [1] work         - Professional, employer context        │
│    [2] home         - Personal projects, learning           │
│    [3] side-project - Independent ventures                  │
│    [4] research     - Academic exploration                  │
│    [5] leisure      - Hobbies and interests                 │
│    [6] other        - Define a custom perspective           │
│                                                             │
│  Selection: _                                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Feature: Domain Selection

```gherkin
Feature: Domain selection within profile
  As a user with a selected profile
  I want to specify domains I work with in this context
  So that Gaius can surface relevant information and connections

  Scenario: Select domains for work profile
    Given the user has selected profile "work"
    When the agent asks about domains
    Then the user can select multiple domains
    And each domain will be framed through the "work" lens

  Scenario: Same domain, different profile framing
    Given the user has profile "work" with domain "weather"
    And the user has profile "leisure" with domain "weather"
    When the user queries about "weather" in "work" profile
    Then results should emphasize NWP models, GRIB data, verification
    When the user queries about "weather" in "leisure" profile
    Then results should emphasize surf reports, golden hour, storm chasing

  Scenario: Domain-specific KB roots
    Given the user selects domain "manufacturing"
    When configuring KB sources
    Then the agent should suggest domain-appropriate paths
    And offer to sync domain-specific agent repositories
```

```
┌─────────────────────────────────────────────────────────────┐
│  Profile: work                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  What domains do you engage with in this context?           │
│                                                             │
│  Select all that apply. The same domain can appear in       │
│  multiple profiles—Gaius will frame it differently based    │
│  on your perspective.                                       │
│                                                             │
│  > [x] weather       - Your expertise area                  │
│    [x] infrastructure - Systems you maintain                │
│    [ ] finance       - Budget, planning                     │
│    [ ] manufacturing - Production systems                   │
│    [+] Add custom domain...                                 │
│                                                             │
│  Continue: [Enter]                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Feature: Credential Isolation

Credentials are managed via **Ansible Vault**, providing encryption-at-rest that integrates with [Multi-Authority CP-ABE](./roadmap-2026Q1.md#multi-authority-cp-abe--r-lwe) for fine-grained, attribute-based access control. This architecture enables encrypted fields and sections within individual KB documents—not just whole-file encryption.

```gherkin
Feature: Profile credential isolation with Ansible Vault
  As a user with multiple profiles
  I want credentials encrypted and isolated between contexts
  So that work and personal resources don't cross-contaminate

  Background:
    Given Ansible Vault is configured for credential storage
    And the user's vault password is cached for this session

  Scenario: Configure work profile credentials
    Given the user is configuring profile "work"
    When adding GitHub integration
    Then the agent should prompt for work-specific credentials
    And encrypt them with Ansible Vault
    And store them isolated from other profiles

  Scenario: Prevent credential leakage
    Given the user has profile "work" with GitHub token A
    And the user has profile "side-project" with GitHub token B
    When operating in "work" profile
    Then only token A should be decryptable
    And token B vault entry should not be accessible

  Scenario: Shared vs isolated integrations
    Given the user is configuring integrations
    When the agent presents each integration
    Then the user can mark it as "shared across profiles" or "profile-specific"
    And shared integrations use a common vault namespace
    And profile-specific use isolated vault namespaces

  Scenario: Encrypted fields in KB documents
    Given a KB document with sensitive sections
    When the document is stored
    Then sensitive fields should be encrypted inline with Ansible Vault
    And CP-ABE policy should control decryption access
    And non-sensitive fields remain plaintext for search indexing

  Scenario: Multi-authority credential access
    Given credentials protected by CP-ABE policy
    And the policy requires attributes from multiple authorities
    When the user has matching attributes from all required authorities
    Then the credential should be decryptable
    When the user lacks attributes from any required authority
    Then decryption should fail with "policy not satisfied"
```

```
┌─────────────────────────────────────────────────────────────┐
│  Profile: work → Credentials (Ansible Vault)                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Credentials are encrypted with Ansible Vault and isolated  │
│  per profile. CP-ABE policies can further restrict access.  │
│                                                             │
│  GitHub:                                                    │
│    Token: [vault encrypted] (work account)                  │
│    Scope: profile-specific                                  │
│    Policy: (profile:work AND device:trusted)                │
│                                                             │
│  Cerebras API:                                              │
│    Key: [vault encrypted]                                   │
│    Scope: [shared / profile-specific]                       │
│    Policy: (role:developer)                                 │
│                                                             │
│  Vault password cached: yes (session)                       │
│                                                             │
│  [ ] I understand these credentials are isolated to "work"  │
│                                                             │
│  Continue: [Enter]                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**See also**: [Multi-Authority CP-ABE + R-LWE](./roadmap-2026Q1.md#multi-authority-cp-abe--r-lwe) for the cryptographic foundation enabling attribute-based access control across federated knowledge bases.

#### Feature: Profile Switching

```gherkin
Feature: Runtime profile switching
  As a user with multiple profiles
  I want to switch perspectives without restarting
  So that I can fluidly move between contexts throughout my day

  Scenario: Switch profile via command
    Given the user is in profile "work"
    When the user executes "/profile leisure"
    Then the active profile should change to "leisure"
    And KB roots should update to leisure paths
    And credentials should swap to leisure credentials
    And the agent swarm should reframe its perspective

  Scenario: Profile switch with unsaved state
    Given the user has unsaved work in profile "work"
    When the user attempts to switch to "home"
    Then the agent should warn about unsaved state
    And offer to save, discard, or cancel

  Scenario: Quick profile indicator
    Given the user is in profile "leisure"
    Then the TUI status bar should show "leisure"
    And the prompt should indicate current profile
```

### Verification

Post-onboarding health check:

```bash
$ gaius-cli --cmd "/health onboarding"

Onboarding Health Check
═══════════════════════

DevEnv:
  ✓ Nix installed (2.18.1)
  ✓ devenv configured
  ✓ Services running (postgres, minio, qdrant)

Integrations:
  ✓ Cerebras API connected (llama-3.3-70b available)
  ✓ xAI Grok API connected (grok-2 available)
  ○ Bytez API not configured (optional)
  ✓ FMP API connected (rate limit: 250/day)

Agents:
  ✓ 3 agent repositories configured
  ✓ 12 agents available
  ✓ Onboarding agent: engineer-manufacturing

Knowledge Base:
  ✓ Manufacturing KB synced (1,247 documents)
  ✓ Vector index built (Qdrant)

Status: Ready ✓
```

---

## Security Considerations

### Credential Management

```hocon
# Use environment variables or secret managers
credentials {
  # Environment variable reference
  cerebras_key = ${CEREBRAS_API_KEY}

  # HashiCorp Vault
  grok_key = ${vault://secret/gaius/xai#api_key}

  # AWS Secrets Manager
  fmp_key = ${aws-sm://gaius/fmp-api-key}

  # 1Password CLI
  subscription_key = ${op://Private/Gaius/subscription-key}
}
```

### Repository Trust

```hocon
agents {
  # Only allow verified publishers
  trust {
    require_signature = true
    allowed_publishers = [
      "gaius-project",
      "acme-corp"
    ]

    # Block known malicious repos
    blocklist = [
      "https://github.com/malicious/*"
    ]
  }

  # Sandbox untrusted agents
  sandbox {
    enabled = true
    network = "restricted"
    filesystem = "read-only"
  }
}
```

---

## CLI Reference

```bash
# Start onboarding
gaius-cli --cmd "/onboarding --profile <profile> --domain <domain>"

# List available profiles
gaius-cli --cmd "/onboarding profiles"

# List available domains
gaius-cli --cmd "/onboarding domains"

# List configured agent repositories
gaius-cli --cmd "/onboarding repos"

# Add agent repository
gaius-cli --cmd "/onboarding repo add <url> --auth <method>"

# Refresh agent cache
gaius-cli --cmd "/onboarding refresh"

# Check onboarding status
gaius-cli --cmd "/health onboarding"

# Reset onboarding
gaius-cli --cmd "/onboarding reset --confirm"
```
