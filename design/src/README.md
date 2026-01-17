# Forward-Deployed Modular Manufacturing (FDMM) + RASE Integration

> **Status**: Design Specification
> **Date**: 2025-12-28
> **Context**: Application of Rapid Agentic Systems Engineering (RASE) to Forward-Deployed Modular Manufacturing

## Overview

This repository contains SysML v2-style specifications for a Forward-Deployed Modular Manufacturing (FDMM) system, grounded in the Basic Formal Ontology (BFO). The design demonstrates how RASE methodology—originally developed for agentic browser automation—can be extended to physical manufacturing systems for autonomous capability development and self-evaluation.

### Thesis

By combining:
1. **BFO-grounded MBSE specifications** (FDMM equipment ontology)
2. **RASE's verifiable closed-loop learning** (Oracle-based V&V)
3. **Magma-8B multimodal methodology** (VLM training on domain-specific data)
4. **Nous Atropos environments** (de novo ontology-based evaluation)

We enable autonomous capability development for manufacturing agents that can:
- Learn manufacturing processes from verifiable examples
- Self-evaluate against formal capability specifications
- Evolve through curriculum-based progression

```mermaid
flowchart TB
    subgraph Ontology["BFO-Grounded Ontology"]
        BFO[Basic Formal Ontology]
        FDMM_Ont[FDMM Equipment Ontology]
        BFO --> FDMM_Ont
    end

    subgraph RASE["RASE Framework"]
        SSM[System State Model<br>Manufacturing State]
        OSM[Operational Scenario Model<br>Work Order Scenarios]
        UOM[UI Observation Model<br>Sensor/Camera Feeds]
        VM[Verifier Model<br>Quality Oracle]
    end

    subgraph Learning["Autonomous Learning Loop"]
        Observe[Observe<br>State Capture]
        Generate[Generate<br>Action Plan]
        Execute[Execute<br>Manufacturing Op]
        Learn[Learn<br>Verified Training]
    end

    FDMM_Ont --> SSM
    SSM --> Observe
    OSM --> Generate
    UOM --> Execute
    VM --> Learn
    Learn --> |"Verified Examples"| Generate
```

---

## Specification Files

| File | Description |
|------|-------------|
| [`FDMM_BFO.sysml.txt`](FDMM_BFO.sysml.txt) | Core FDMM system specification with BFO grounding |
| [`FDMM_RearEchelon_Augmentation.sysml.txt`](FDMM_RearEchelon_Augmentation.sysml.txt) | Rear-echelon facility augmentation package |

---

## BFO Grounding

The FDMM specifications map manufacturing concepts to BFO's upper ontology, enabling rigorous formal reasoning and interoperability with other BFO-aligned ontologies.

```mermaid
classDiagram
    class BFO_Entity {
        <<abstract>>
    }
    class BFO_Continuant {
        <<abstract>>
        Entities persisting through time
    }
    class BFO_Occurrent {
        <<abstract>>
        Processes/events
    }
    class BFO_IndependentContinuant {
        <<abstract>>
        Material entities
    }
    class BFO_RealizableEntity {
        <<abstract>>
        Functions, dispositions
    }
    class BFO_Process {
        <<abstract>>
        Temporal occurrences
    }

    BFO_Entity <|-- BFO_Continuant
    BFO_Entity <|-- BFO_Occurrent
    BFO_Continuant <|-- BFO_IndependentContinuant
    BFO_Continuant <|-- BFO_RealizableEntity
    BFO_Occurrent <|-- BFO_Process

    class Equipment {
        equipId: String
        makeModel: String
        mass_kg: kg
        handling: HandlingClass
    }
    class Capability {
        capabilityId: String
        description: String
    }
    class ManufacturingProcess {
        processId: String
        description: String
    }
    class Container_Module {
        moduleId: String
        containerType: ContainerType
    }

    BFO_IndependentContinuant <|-- Equipment
    BFO_IndependentContinuant <|-- Container_Module
    BFO_RealizableEntity <|-- Capability
    BFO_Process <|-- ManufacturingProcess

    Container_Module "1" *-- "*" Equipment : contains
    Container_Module "1" *-- "*" Capability : bears
    Capability "1" --> "*" ManufacturingProcess : realized by
```

### BFO Mappings

| BFO Concept | FDMM Instantiation | Example |
|-------------|-------------------|---------|
| `BFO:IndependentContinuant` | Equipment, Modules, Sites | Haas VF-2YT VMC, 40ft HC Container |
| `BFO:RealizableEntity` | Capabilities borne by modules | `Cap_MachinePrismatic_CNC` |
| `BFO:Process` | Manufacturing operations | `P_CNC_Mill`, `P_WeldAndFabricate` |
| `BFO:Quality` | Constraints and requirements | Power quality, vibration isolation |

---

## FDMM Physical Architecture

The system consists of modular containerized manufacturing cells, yard operations, and optional rear-echelon augmentation.

```mermaid
flowchart TB
    subgraph Deployment["FDMM Deployment Site"]
        direction TB

        subgraph Utilities["Utilities"]
            Power[Power Distribution]
            Air[Compressed Air<br>25HP Compressor]
            Net[Data Network]
        end

        subgraph Containers["Container Modules (5x 40ft HC)"]
            Manual[Manual Machining<br>Lathes, Mills, Grinders]
            CNC[CNC Machining<br>VMC, CNC Lathe, CAD/CAM]
            Cut[Cutting & Prep<br>Saws, Plasma]
            Weld[Welding & Fab<br>TIG/MIG, Stud Welder]
            Finish[Finishing<br>Deburr, Grind]
        end

        subgraph Yard["Yard Operations"]
            Fork[Forklifts<br>2500#, 5000#]
            Truck[Flatbed Truck<br>F-450]
        end
    end

    Utilities --> |"Power, Air, Data"| Containers
    Yard --> |"Material Flow"| Containers

    subgraph RearEchelon["Rear-Echelon Augmentation (Optional)"]
        LargeTurn[Large Turning<br>22x120 Lathes]
        EDM[Wire EDM<br>Sodick AQ327L]
        Grind[Precision Grinding<br>DCM Rotary]
        Press[Stamping<br>35 Ton OBI]
        QA[QA & Dispatch]
    end

    Containers <--> |"Work Orders<br>Finished Goods"| RearEchelon
```

### Container Module Specifications

```mermaid
flowchart LR
    subgraph Module["Container Module Template"]
        direction TB

        subgraph Ports["Interface Ports"]
            PWR[pwrIn: ElectricalPower]
            AIR[airIn: CompressedAir]
            NET[netIn: DataNet]
            HEAT[heatOut: HeatRejection]
            MAT_IN[matIn: MaterialFlow]
            MAT_OUT[matOut: MaterialFlow]
        end

        subgraph Qualities["Deployment Qualities"]
            ENV[envControl: Class]
            POWER[powerDemand: kW]
            THERMAL[thermalLoad: kW]
        end

        subgraph Caps["Capabilities"]
            C1[Capability 1]
            C2[Capability 2]
        end

        subgraph Equip["Equipment"]
            E1[Equipment 1]
            E2[Equipment 2]
        end
    end
```

---

## Capability Taxonomy

Manufacturing capabilities are classified by their primary mission contribution.

```mermaid
mindmap
  root((FDMM Capabilities))
    Sustainment & Repair
      Cut and Prep Stock
      Join and Fabricate
      Machine Rotational - Manual
      Machine Prismatic - Manual
      Finish and Deburr
      Restore Fits - Hone/Grind
      Heat Treat - Limited
    Low-Rate Production
      Machine Rotational - CNC
      Machine Prismatic - CNC
    Metrology & Process Assurance
      Design/Plan/Program - CAD/CAM
    Deployment & Logistics
      Handle Materials - Yard
    Rear-Echelon Augmentation
      Large Envelope Turning
      Wire EDM Precision
      Rotary Grinding Precision
      Heavy Stamping/Punching
      Advanced Heat Treat
      Production Turret Turning
```

---

## RASE Integration for Manufacturing

### The Four Coupled Models

RASE extends to manufacturing by mapping its four models to manufacturing-specific concerns:

```mermaid
flowchart TB
    subgraph OSM["OSM: Operational Scenario Model"]
        WorkOrder[Work Order Scenario<br>BDD-style specification]
        Steps[Given/When/Then Steps<br>- Initial stock state<br>- Manufacturing operations<br>- Quality criteria]
    end

    subgraph SSM["SSM: System State Model"]
        MfgState[Manufacturing State<br>as Typed Graph]
        Equipment_State[Equipment Status]
        Material_State[Material Inventory]
        WIP[Work-in-Progress]
    end

    subgraph UOM["UOM: UI Observation Model"]
        Sensors[Sensor Observations<br>- Machine telemetry<br>- Camera feeds<br>- CMM data]
        Marks[Set-of-Mark Grounding<br>- Feature recognition<br>- Defect detection]
    end

    subgraph VM["VM: Verifier Model"]
        Requirements[Manufacturing Requirements<br>- Tolerances<br>- Surface finish<br>- Fit specifications]
        Oracle[Quality Oracle<br>- CMM verification<br>- Semantic diff]
        Reward[Reward Strategy<br>- Binary: pass/fail<br>- Graded: partial credit]
    end

    OSM --> |"Specifies"| SSM
    SSM --> |"Ground Truth"| VM
    UOM --> |"Training Target"| VM
    VM --> |"Verified Examples"| OSM
```

### Manufacturing Scenario Example

```gherkin
Feature: Shaft Repair and Fit Restoration

  Background:
    Given the CNC machining module is operational
    And the honing station is calibrated to ±0.0005"

  Scenario: Restore worn bearing journal
    Given a shaft with journal wear of 0.005" undersize
    When the agent plans the restoration sequence
    And the agent executes:
      | Operation     | Equipment        | Target          |
      | Rough turn    | CNC Lathe        | +0.010" oversize|
      | Finish turn   | CNC Lathe        | +0.002" oversize|
      | Hone          | Sunnen LBB-1660  | Nominal ±0.0001"|
    Then the journal diameter should be within tolerance
    And the surface finish should be ≤ 16 µin Ra
    And the semantic accuracy should be at least 0.95
```

### Verification Flow

```mermaid
sequenceDiagram
    participant WO as Work Order
    participant Agent as Manufacturing Agent
    participant Equip as Equipment (CNC/Hone)
    participant Oracle as Quality Oracle (CMM)
    participant Train as Training Pipeline

    WO->>Agent: Scenario specification
    Agent->>Agent: Plan operations (VLM inference)
    Agent->>Equip: Execute machining sequence
    Equip->>Oracle: Part for inspection

    Oracle->>Oracle: CMM measurement
    Oracle->>Oracle: Semantic diff vs. spec

    alt Pass (accuracy ≥ threshold)
        Oracle->>Train: Verified positive example
        Train->>Agent: Update model weights
    else Fail
        Oracle->>Train: Verified negative example
        Train->>Agent: Curriculum adjustment
    end
```

---

## Magma-8B Methodology for Manufacturing

The Magma-8B approach—training VLMs on domain-specific action traces—maps naturally to manufacturing:

```mermaid
flowchart TB
    subgraph Data["Training Data Generation"]
        direction LR
        Scenario[BDD Scenarios]
        Execution[Agent Execution]
        Trace[Action Trace<br>+ Machine Vision]
        Verify[Oracle Verification]

        Scenario --> Execution --> Trace --> Verify
    end

    subgraph Traces["Trace Components"]
        direction TB
        Screenshots[Machine Camera Frames]
        SoM[Set-of-Mark Annotations<br>- Workpiece features<br>- Tool positions<br>- Display readings]
        Actions[Action Sequence<br>- G-code commands<br>- Feed/speed params<br>- Tool changes]
    end

    subgraph VLM["VLM Training"]
        direction LR
        Base[Base Model<br>Magma-8B]
        Finetune[Fine-tune on<br>Manufacturing Traces]
        MfgVLM[Manufacturing VLM]

        Base --> Finetune --> MfgVLM
    end

    Data --> Traces
    Traces --> VLM

    subgraph Deploy["Deployment"]
        MfgVLM --> |"Inference"| NewScenario[New Work Order]
        NewScenario --> |"Actions"| Machine[CNC/Manual Equipment]
    end
```

### Set-of-Mark for Manufacturing

Just as RASE uses SoM to ground VLM actions in browser UI elements, manufacturing SoM grounds actions in:

| SoM Category | Browser Domain | Manufacturing Domain |
|--------------|----------------|---------------------|
| **Interactable** | Buttons, inputs | Tool positions, control surfaces |
| **Reference** | Text labels | Display readings, dimension callouts |
| **Region** | Content areas | Workpiece surfaces, feature zones |
| **Status** | Indicators | Machine state LEDs, error codes |

---

## Nous Atropos Integration

Nous Atropos provides RL environments for agent self-evaluation. For FDMM, we create manufacturing-specific environments:

```mermaid
flowchart TB
    subgraph Atropos["Nous Atropos Environment"]
        direction TB

        subgraph State["Manufacturing State Space"]
            Inventory[Material Inventory]
            WIP[Work-in-Progress Parts]
            Equipment_Status[Equipment Status]
            Measurements[CMM Measurements]
        end

        subgraph Actions["Action Space"]
            Select[Select Equipment]
            Program[Program Operation]
            Execute_Op[Execute Cut/Weld/Grind]
            Measure[Request Measurement]
        end

        subgraph Reward["Reward Function (RLVR)"]
            Tolerance[Tolerance Compliance]
            Finish[Surface Finish Quality]
            Time[Cycle Time]
            Scrap[Scrap Rate]
        end
    end

    subgraph Oracle["Verifiable Oracle"]
        CMM[CMM Ground Truth]
        CAD[CAD Model Comparison]
        API[Equipment API State]
    end

    State --> Agent[Manufacturing Agent]
    Agent --> Actions
    Actions --> State
    Oracle --> Reward
    Reward --> Agent
```

### Ontology-Based Evaluation

The BFO-grounded ontology enables de novo evaluation:

1. **New Part Classes**: Ontology defines capability requirements for novel parts
2. **Compositional Scenarios**: Combine primitive capabilities into complex workflows
3. **Transfer Learning**: BFO alignment enables knowledge transfer from related domains

```mermaid
flowchart LR
    subgraph Ontology["BFO-Grounded Ontology"]
        Part[Part Definition<br>- Features<br>- Tolerances<br>- Material]
        Caps[Required Capabilities<br>- Turning<br>- Milling<br>- Heat Treat]
    end

    subgraph Gen["Scenario Generation"]
        Template[Scenario Template]
        Instantiate[Instantiate from Ontology]
        Novel[Novel Part Scenario]
    end

    subgraph Eval["De Novo Evaluation"]
        Agent2[Agent]
        Execute2[Execute on Novel Part]
        Verify2[Oracle Verification]
    end

    Part --> Caps
    Caps --> Instantiate
    Template --> Instantiate
    Instantiate --> Novel
    Novel --> Agent2
    Agent2 --> Execute2
    Execute2 --> Verify2
```

---

## Requirements and V&V Alignment

FDMM requirements map to RASE verification methods following the V-model:

```mermaid
flowchart TB
    subgraph Left["Definition (Left V-side)"]
        direction TB
        Stakeholder[Stakeholder Needs<br>Forward sustainment, repair capability]
        System[System Requirements<br>DEP-001: Container deployability<br>CAP-001: Part fabrication envelope]
        Arch[Architecture<br>Module structure, interfaces]
        Design[Detailed Design<br>Equipment selection, layout]
    end

    subgraph Right["Verification (Right V-side)"]
        direction TB
        Validation[System Validation<br>Operational effectiveness in theater]
        SysVerify[System Verification<br>BDD scenario execution]
        IntTest[Integration Testing<br>Multi-module coordination]
        CompTest[Component Testing<br>Equipment capability probes]
    end

    Stakeholder --> Validation
    System --> SysVerify
    Arch --> IntTest
    Design --> CompTest

    subgraph Impl["Implementation"]
        Training[Agent Training<br>Verified examples]
        Deploy[Deployment<br>Module setup]
    end

    Design --> Impl
    Impl --> CompTest
```

### Verification Cases

| Verification Case | Method | RASE Mapping |
|-------------------|--------|--------------|
| VC-001: Power Budget | Analysis | `Constraint` composition |
| VC-002: Reference Part Set | Demonstration | `BDDScenario` execution |
| VC-003: Container Fit | Inspection | `SSM` state validation |
| VC-004: Capability Coverage | Analysis | `ScenarioRequirement` coverage |

---

## Digital Thread

RASE's `TraceableId` provides full traceability from equipment list to verified training samples:

```mermaid
flowchart LR
    subgraph Source["Source Artifacts"]
        Equip[Equipment List<br>Kingston 21x120 Lathe]
        Spec[SysML Specification<br>FDMM_BFO.sysml.txt]
    end

    subgraph Model["Model Elements"]
        EquipDef[Equipment Definition<br>nifi://FDMM/equip/lathe-001]
        CapDef[Capability Definition<br>rase://FDMM/cap/turn-manual]
        Scenario[BDD Scenario<br>bdd://features/shaft_repair#restore_journal]
    end

    subgraph Execution["Execution Artifacts"]
        Run[Scenario Run<br>rase://run/uuid-xxx]
        Trace[Action Trace<br>rase://trace/uuid-yyy]
        Verification[Verification Result<br>rase://verify/uuid-zzz]
    end

    subgraph Training["Training Artifacts"]
        Example[Verified Example<br>rase://example/uuid-aaa]
        Model_v[Model Version<br>rase://model/mfg-vlm-1.2.3]
    end

    Equip --> EquipDef
    Spec --> EquipDef
    EquipDef --> CapDef
    CapDef --> Scenario
    Scenario --> Run
    Run --> Trace
    Run --> Verification
    Verification --> Example
    Example --> Model_v
```

---

## Implementation Roadmap

### Phase 1: Ontology Foundation
- [ ] Formalize BFO mappings in OWL/RDF
- [ ] Create JSON-LD contexts for equipment and capabilities
- [ ] Validate against BFO conformance tests

### Phase 2: SSM for Manufacturing
- [ ] Implement `ManufacturingState` as typed graph
- [ ] Equipment API adapters (CNC controllers, CMM)
- [ ] State capture and comparison primitives

### Phase 3: OSM Scenarios
- [ ] Define step library for manufacturing operations
- [ ] Gherkin templates for common workflows
- [ ] Scenario parameterization from part ontology

### Phase 4: UOM for Shop Floor
- [ ] Machine vision integration (camera feeds)
- [ ] SoM generation for workpiece features
- [ ] Trace recording for action sequences

### Phase 5: VM and Oracle
- [ ] CMM integration for ground truth
- [ ] Semantic diff for part comparison
- [ ] Reward strategy calibration

### Phase 6: Atropos Integration
- [ ] Manufacturing environment definition
- [ ] Curriculum levels based on part complexity
- [ ] Self-evaluation metrics

---

## References

### RASE Framework
- [RASE MBSE Framework](../docs/scratch/2025-12-19/150000_rase_mbse_framework.md) - Core methodology documentation
- [gaius.rase package](../src/gaius/rase/) - Python implementation

### Ontology Standards
- [Basic Formal Ontology (BFO)](https://basic-formal-ontology.org/) - Upper ontology foundation
- [SysML v2](https://www.omg.org/spec/SysML/) - Systems modeling language

### Related Work
- [Magma-8B](https://arxiv.org/abs/2502.XXXXX) - Multimodal VLM methodology
- [Nous Atropos](https://github.com/NousResearch/atropos) - RL environments for agents

---

## License

Apache 2.0 - See repository root for details.
