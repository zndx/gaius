You’re right to sharpen this—the CP vs KP distinction fundamentally shapes the access control semantics. Let me search for the canonical MA-ABE literature to ensure I’m grounding this properly.​​​​​​​​​​​​​​​​
 
 Excellent—this grounds us properly. The Chase (TCC 2007) paper established MA-ABE, and the critical distinction you’re highlighting maps directly to who controls access policy and when:
 
 **CP-ABE**: Policy embedded in ciphertext at encryption time → *author-controlled disclosure*
 **KP-ABE**: Policy embedded in user keys by authorities → *governance-controlled access*
 
 For KB interop, you likely need **both** operating in tandem. Let me work through the hypermedia extension.
 
 ## CP-ABE vs KP-ABE in KB Context
 
 ```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                        Access Control Topology                          │
 ├─────────────────────────────────┬───────────────────────────────────────┤
 │           CP-ABE                │              KP-ABE                   │
 │   (Author-Controlled)           │      (Authority-Controlled)           │
 ├─────────────────────────────────┼───────────────────────────────────────┤
 │ "I encrypt my API key so only   │ "Our compliance authority issues     │
 │  DevOps + NDA_Signed can read"  │  keys that can only decrypt PII      │
 │                                 │  labeled content to HR users"        │
 ├─────────────────────────────────┼───────────────────────────────────────┤
 │ Policy travels WITH ciphertext  │ Policy lives in user's key           │
 │ Encryptor chooses recipients    │ Authority chooses what user can see  │
 │ Good for: ad-hoc sharing        │ Good for: compliance, audit, RBAC    │
 └─────────────────────────────────┴───────────────────────────────────────┘
 ```
 
 In your FedWiki scenario, **CP-ABE** handles horizontal sharing (author → peers), while **KP-ABE** handles vertical governance (authority → classes of content).
 
 ## Inline Encrypted Hypermedia Syntax
 
 For Markdown, we need a syntax that carries:
 
 1. Semantic type annotation (what IS this, even if encrypted)
 1. ABE mode indicator (CP vs KP)
 1. Ciphertext (inline or by reference)
 1. Policy expression (for CP-ABE) or attribute set (for KP-ABE)
 
 ```markdown
 ## Deployment Configuration
 
 The production API endpoint is `https://api.example.com/v2`.
 
 Authentication requires: <!--abe:cp
   @type: kb:Credential/APIKey
   @policy: "(Cloudera.DevOps AND Env.Production) OR Cloudera.SRE"
   @stats: { entropy: 256, rotation: "90d" }
   @ref: solid://pod.example/kb/secrets/col-api-keys#row-prod
 -->████████████████<!--/abe-->
 
 For staging, use: <!--abe:cp
   @type: kb:Credential/APIKey  
   @policy: "Cloudera.Engineering"
   @inline: "YWJjZGVm...base64-ciphertext..."
 -->████████████████<!--/abe-->
 ```
 
 The rendered view shows redaction blocks, but the semantic metadata is parseable.
 
 ## RDF Representation of Encrypted Inline Spans
 
 ```turtle
 @prefix kb: <https://yourspec.org/kb#> .
 @prefix abe: <https://yourspec.org/abe#> .
 @prefix frag: <https://yourspec.org/fragment#> .
 
 # The document itself
 <https://pod.example/kb/docs/deployment.md>
   a kb:Document ;
   kb:hasEncryptedFragment <#frag-1>, <#frag-2> .
 
 # Fragment 1: Referenced ciphertext (in a Base)
 <https://pod.example/kb/docs/deployment.md#frag-1>
   a frag:InlineEncryptedSpan ;
   frag:byteOffset 847 ;
   frag:byteLength 32 ;
   abe:mode abe:CP-ABE ;
   abe:semanticType kb:Credential, kb:APIKey ;
   abe:policy "(Cloudera.DevOps AND Env.Production) OR Cloudera.SRE" ;
   abe:ciphertextRef <https://pod.example/kb/bases/secrets#col-api-keys/row-prod> ;
   abe:statistics [
     abe:entropy 256 ;
     abe:rotationPolicy "P90D"^^xsd:duration
   ] .
 
 # Fragment 2: Inline ciphertext
 <https://pod.example/kb/docs/deployment.md#frag-2>
   a frag:InlineEncryptedSpan ;
   frag:byteOffset 1203 ;
   frag:byteLength 32 ;
   abe:mode abe:CP-ABE ;
   abe:semanticType kb:Credential, kb:APIKey ;
   abe:policy "Cloudera.Engineering" ;
   abe:ciphertextInline "YWJjZGVm..."^^xsd:base64Binary .
 ```
 
 ## Hypermedia Reference Architecture
 
 The key insight: ciphertext can live **anywhere** in the federated graph, and Solid gives us the linking semantics:
 
 ```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                     Hypermedia Ciphertext Topology                      │
 └─────────────────────────────────────────────────────────────────────────┘
 
 ┌──────────────────┐
 │  Markdown Doc    │
 │  (KB-A)          │
 │ ─────────────────│      abe:ciphertextRef
 │ ...config...     │ ─────────────────────────┐
 │ <!--abe:cp       │                          │
 │   @ref: ...      │                          ▼
 │ -->████<!--/abe->│               ┌─────────────────────┐
 └──────────────────┘               │  Encrypted Base     │
                                    │  (KB-A or KB-B!)    │
 ┌──────────────────┐               │ ────────────────────│
 │  FedWiki Page    │               │  col: api_keys      │
 │  (KB-C)          │               │  ┌────┬───────────┐ │
 │ ─────────────────│               │  │row │ ciphertext│ │
 │ [[xref:KB-A/...]]│──────────────►│  ├────┼───────────┤ │
 │                  │  transclusion │  │prod│ 0x8a3f... │ │
 └──────────────────┘               │  │stg │ 0x2b1c... │ │
                                    │  └────┴───────────┘ │
                                    └─────────────────────┘
 ```
 
 ## Cross-KB Xref Semantics
 
 For FedWiki-style transclusion of encrypted content across KBs:
 
 ```turtle
 @prefix xref: <https://yourspec.org/xref#> .
 @prefix abe: <https://yourspec.org/abe#> .
 
 # A cross-KB reference to encrypted content
 <https://fedwiki.example/page-x#para-3>
   a xref:Transclusion ;
   xref:sourceKB <https://pod.ryan.example/kb/> ;
   xref:sourceFragment <https://pod.ryan.example/kb/docs/arch.md#frag-7> ;
   xref:transclusionMode xref:EncryptedPassthrough ;
   
   # Metadata ABOUT the encrypted content (itself possibly encrypted!)
   abe:disclosedMetadata [
     abe:semanticType kb:ArchitectureDecision ;
     abe:disclosureLevel abe:Schema ;
     abe:policy "FedWiki.Contributor"  # Policy to see THIS metadata
   ] ;
   
   # The actual encrypted content reference
   abe:encryptedContent [
     abe:ciphertextRef <https://pod.ryan.example/kb/docs/arch.md#frag-7> ;
     abe:policy "(Cloudera.Engineering AND FedWiki.Contributor)" ;
     abe:mode abe:CP-ABE
   ] .
 ```
 
 ## Layered Metadata Encryption for Xrefs
 
 This is where it gets recursive. The **metadata about what’s encrypted** can itself be encrypted at different disclosure levels:
 
 ```json
 {
   "@context": { /* ... */ },
   "@id": "https://fedwiki.example/page-x#para-3",
   "@type": "xref:Transclusion",
   
   "xref:sourceKB": "https://pod.ryan.example/kb/",
   
   "abe:metadataLayers": [
     {
       "abe:disclosureLevel": "Existence",
       "abe:policy": "FedWiki.Reader",
       "abe:reveals": {
         "abe:fragmentExists": true,
         "abe:sourceKBDomain": "pod.ryan.example"
       }
     },
     {
       "abe:disclosureLevel": "Name", 
       "abe:policy": "FedWiki.Contributor",
       "abe:reveals": {
         "abe:ciphertextInline": "Zm9v..."  // Encrypted fragment title
       }
     },
     {
       "abe:disclosureLevel": "Schema",
       "abe:policy": "(FedWiki.Contributor AND Partner.NDA)",
       "abe:reveals": {
         "abe:semanticType": "kb:ArchitectureDecision",
         "abe:hasProperties": ["kb:rationale", "kb:alternatives", "kb:decision"]
       }
     },
     {
       "abe:disclosureLevel": "Values",
       "abe:policy": "(Cloudera.Engineering AND FedWiki.Contributor AND Partner.NDA)",
       "abe:ciphertextRef": "https://pod.ryan.example/kb/docs/arch.md#frag-7"
     }
   ]
 }
 ```
 
 ## Dual-Policy ABE for Governance + Author Control
 
 For scenarios requiring both CP-ABE and KP-ABE simultaneously—author sets sharing policy, but governance layer restricts what attribute-holders can decrypt:
 
 ```turtle
 <https://pod.example/kb/bases/hr-data#col-salary>
   a kb:BaseColumn ;
   
   # CP-ABE: Author's sharing intent
   abe:cpPolicy "(HR.Manager OR Finance.Payroll)" ;
   
   # KP-ABE: Governance constraint (user must have key with matching policy)
   abe:kpAttributeSet [ abe:attr "PII.Compensation", "DataClass.Confidential" ] ;
   
   # Effective access = CP-policy satisfaction ∧ KP-key policy match
   abe:accessSemantics abe:ConjunctiveDualPolicy .
 ```
 
 The decryption succeeds only if:
 
 1. User’s attributes satisfy the CP-ABE policy in the ciphertext, AND
 1. User’s KP-ABE key policy is satisfied by the attribute labels on the ciphertext
 
 ## Spec Structure Update
 
 ```
 kb-interop-spec/
 ├── ontology/
 │   ├── kb-core.ttl
 │   ├── abe-core.ttl              # Base ABE primitives
 │   ├── abe-cp.ttl                # CP-ABE specific
 │   ├── abe-kp.ttl                # KP-ABE specific  
 │   ├── abe-dual-policy.ttl       # Combined CP+KP semantics
 │   └── xref-encrypted.ttl        # Cross-KB encrypted references
 ├── syntax/
 │   ├── markdown-abe.md           # Inline encryption syntax
 │   ├── markdown-abe.pest         # Formal grammar (PEG)
 │   └── rendering.md              # How UIs should render ████
 ├── protocols/
 │   ├── solid-abe-binding.md      # Solid + ABE integration
 │   ├── fedwiki-transclusion.md   # Encrypted xref semantics
 │   └── authority-federation.md   # MA trust topology
 └── crypto/
     ├── cp-abe-instantiation.md   # Recommended CP-ABE scheme
     ├── kp-abe-instantiation.md   # Recommended KP-ABE scheme
     └── dual-policy-construction.md
 ```
 
 ## Implementation Path
 
 Given your Flink/Spark background, you could build a streaming processor that:
 
 1. Parses Markdown for `<!--abe:...-->` spans
 1. Extracts semantic metadata → pushes to Solid pod as RDF
 1. Resolves `@ref` hypermedia links to Base columns
 1. Maintains a materialized view of “what can user X see” given their attribute set

