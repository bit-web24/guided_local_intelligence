# Clarification Stage — Practical Examples

## Problem: Before vs After

### Scenario 1: Vague Initial Request

#### BEFORE (Without Clarification)
```
User: "Fix the code"
         ↓
Agent thinks: "Maybe refactor? Maybe fix bugs? Maybe optimize?"
         ↓
Plan created:
1. Review code for bugs
2. Optimize performance
3. Refactor structure
4. Add error handling
         ↓
Execution wastes time on optimization when user only wanted bug fixes
         ↓
Result: Misaligned output, refinement loop needed
```

#### AFTER (With Clarification)
```
User: "Fix the code"
         ↓
Agent asks for clarification:

**Understanding:** Identify and fix bugs in the codebase

**Goals:**
- Find runtime errors
- Fix logic errors
- Verify fixes work

**Scope:**
- Includes: Bug fixes only
- Doesn't include: Refactoring, optimization, new features

**Questions:**
- What type of bugs? (Runtime, logic, syntax?)
- Should I run tests to verify?
         ↓
User confirms: "Yes, but also run tests"
         ↓
Plan created (correct understanding):
1. Identify runtime errors
2. Fix identified bugs
3. Run test suite
4. Report results
         ↓
Execution is focused and aligned
         ↓
Result: Correct output on first try
```

---

## Scenario 2: Task with Hidden Complexity

### Case: "Document the project"

#### BEFORE
```
Prompt: "Document the project"
         ↓
Agent plans:
1. Create README
2. Add installation steps
3. Write usage guide
         ↓
User expected: Architecture docs, API reference, contribution guide
Result: Mismatch on first execution
```

#### AFTER
```
Prompt: "Document the project"
         ↓
Agent clarifies:

**Understanding:** Create comprehensive documentation for the project

**Goals:**
- Write project overview and features
- Document setup and installation
- Provide usage examples
- Explain project architecture

**Scope:**
- Includes: README, setup guide, architecture docs
- Doesn't include: API docs, contribution guide, troubleshooting

**Questions:**
- Should I include API endpoint documentation?
- Do you want contribution guidelines documented?
- Should I create a troubleshooting section?
         ↓
User refines: "Include API documentation, skip contribution guide"
         ↓
Agent re-clarifies:

**Updated Understanding:** Create documentation including README, setup, usage, architecture, and API reference

**Goals:**
1. Write README with project overview
2. Document setup and installation
3. Create API documentation
4. Explain architecture decisions
5. Provide usage examples

**Scope:**
- Includes: README, setup, API docs, architecture, examples
- Doesn't include: Contribution guide, changelog, troubleshooting
         ↓
User confirms: "Yes, this is exactly what I need"
         ↓
Perfect plan created based on confirmed understanding
```

---

## Scenario 3: Context-Specific Task

### Case: Working with a specific codebase

#### BEFORE
```
Prompt: "Find all API endpoints"
Path: "/home/user/ecommerce"
         ↓
Agent plans generally:
1. Search for endpoint definitions
2. List all endpoints
3. Describe functionality
         ↓
Uncertain about: Which framework? Which pattern? REST or GraphQL?
Result: Generic approach, might miss some endpoints
```

#### AFTER
```
Prompt: "Find all API endpoints"
Path: "/home/user/ecommerce"
         ↓
Agent clarifies (with path context):

**Understanding:** Locate and document all API endpoints in the ecommerce application

**Goals:**
- Identify all HTTP endpoints
- Determine methods (GET, POST, PUT, DELETE)
- Extract route paths and parameters
- Summarize endpoint functionality

**Scope:**
- Includes: All REST endpoints in the project
- Doesn't include: Internal utilities, database functions

**Questions:**
- Should I include request/response schemas?
- Do you want authentication requirements documented?
- Should I check for deprecated endpoints?
         ↓
User refines: "Include schemas and auth requirements. Mark any deprecated endpoints."
         ↓
Agent re-clarifies:

**Updated Understanding:** Find all REST API endpoints, document their methods, paths, parameters, schemas, authentication requirements, and note any deprecated endpoints

**Goals:**
1. Scan codebase for endpoint definitions
2. Extract route, method, and handler info
3. Document request/response schemas
4. List authentication requirements
5. Identify deprecated endpoints
6. Create organized endpoint reference

**Scope:**
- Includes: REST endpoints, schemas, auth requirements, deprecations
- Doesn't include: WebSocket, internal utilities, database functions
         ↓
User confirms: "Perfect"
         ↓
Targeted plan created, finds all endpoints with full details
```

---

## Scenario 4: Ambiguous Scope

### Case: "Improve performance"

#### BEFORE
```
Prompt: "Improve performance"
         ↓
Agent guesses scope:
- Could mean CPU optimization
- Could mean memory optimization
- Could mean API response time
- Could mean database queries
         ↓
Plan picks one randomly:
1. Optimize database queries
2. Add caching
3. Profile results
         ↓
User wanted: Reduce API response time, not database optimization
Result: Wrong focus, wasted effort
```

#### AFTER
```
Prompt: "Improve performance"
         ↓
Agent clarifies:

**Understanding:** Improve performance of the application

**Goals:**
- Identify performance bottlenecks
- Optimize code/infrastructure
- Measure improvements
- Document changes

**Scope:**
- Includes: All performance improvements
- Doesn't include: New features, UI improvements

**Questions:**
- What aspect of performance? (API response time, CPU, memory, database?)
- What's the target performance improvement? (50% faster? Load in <2s?)
- Which parts of the application are most critical?
- Should I profile existing performance first?
         ↓
User refines: "API endpoint response time. Currently 5s, target <2s. Start with profiling."
         ↓
Agent re-clarifies:

**Updated Understanding:** Reduce API endpoint response time from 5 seconds to under 2 seconds by profiling and optimizing bottlenecks

**Goals:**
1. Profile current API performance
2. Identify response time bottlenecks
3. Optimize identified bottlenecks
4. Test responses (verify <2s)
5. Document optimizations made

**Scope:**
- Includes: API endpoints, response time optimization, profiling
- Doesn't include: Database optimization (unless it's an endpoint bottleneck), UI changes

**Questions Resolved:**
- Focus: API endpoints only ✓
- Target: <2 seconds response time ✓
- Approach: Profiling-first ✓
         ↓
User confirms: "Exactly"
         ↓
Targeted, measurable plan created
```

---

## Scenario 5: First-Time User

### Case: User unfamiliar with project asks for help

#### BEFORE
```
Prompt: "Add authentication to the app"
         ↓
Agent might:
- Assume Flask/Django (it's Python)
- Assume session-based auth
- Assume no existing auth
- Guess at implementation approach
         ↓
Execution creates unsuitable solution
         ↓
Result: Rework needed, frustration
```

#### AFTER
```
Prompt: "Add authentication to the app"
Path: "/home/user/my_app"
         ↓
Agent clarifies:

**Understanding:** Implement user authentication for the application

**Goals:**
- Add login/signup functionality
- Manage user sessions
- Secure password handling
- Protect routes with authentication

**Scope:**
- Includes: User auth implementation
- Doesn't include: Authorization, role-based access, OAuth

**Questions:**
- What's the tech stack? (Framework, language, database?)
- Should I use JWT or session-based authentication?
- Any existing partial auth implementation?
- Do you need user registration or just login?
- Should there be a "remember me" feature?
         ↓
User refines: "It's a Flask app. JWT auth. Registration needed. Check the codebase for existing auth code."
         ↓
Agent scans project (because of --path):
- Finds Flask app
- Discovers partial JWT setup
- Sees User model exists
         ↓
Agent re-clarifies:

**Updated Understanding:** Complete JWT-based authentication in Flask app with user registration, leveraging existing User model and partial JWT setup

**Goals:**
1. Examine existing JWT and User model code
2. Implement user registration endpoint
3. Implement login endpoint (with JWT generation)
4. Create logout/token refresh endpoints
5. Add authentication decorators for protected routes
6. Test complete auth flow

**Scope:**
- Includes: JWT setup, registration, login, protected routes
- Doesn't include: Password reset, email verification, OAuth
- Leverages: Existing User model, existing JWT library

**Key Context:**
- Tech stack: Flask application ✓
- Auth type: JWT ✓
- Includes: Registration ✓
- Existing code: User model + partial JWT ✓
         ↓
User confirms: "Perfect, this is exactly what I need"
         ↓
Perfectly tailored plan created based on actual project state
```

---

## Real-World Impact Comparison

### Project: Add feature to payment system

#### Timeline WITHOUT Clarification
```
Day 1, 2pm: User submits task "Add payment feature"
Day 1, 2:15pm: Agent creates plan (guesses intent)
Day 1, 2:20pm-4pm: Agent executes 5 steps
Day 1, 4pm: User reviews result: "This is not what I wanted"
Day 2, 10am: Task is submitted again with clarifications
Day 2, 10:15am: Agent creates new plan
Day 2, 10:20am-2pm: Agent executes (with correct understanding)
Day 2, 2pm: User reviews result: ✓ Correct

Time wasted: 1.5 days + 2 execution cycles
```

#### Timeline WITH Clarification
```
Day 1, 2pm: User submits task "Add payment feature"
Day 1, 2:05pm: Agent clarifies understanding
Day 1, 2:10pm: User confirms clarification: "Yes, exactly"
Day 1, 2:15pm: Agent creates perfect plan
Day 1, 2:20pm-4pm: Agent executes (correct understanding from start)
Day 1, 4pm: User reviews result: ✓ Correct

Time saved: 1 day + avoided second execution cycle
```

---

## Common Clarification Patterns

### Pattern 1: Scope Definition
```
User: "Optimize the system"

Agent clarifies:
**Questions:**
- What component? (Backend, frontend, database, infrastructure?)
- What metric? (Speed, memory, cost, throughput?)
- What's the acceptable tradeoff? (Complexity vs. performance?)

Result: User provides specific scope, plan is targeted
```

### Pattern 2: Success Criteria
```
User: "Improve code quality"

Agent clarifies:
**Questions:**
- What does "improved" mean? (More tests? Fewer bugs? Better style?)
- What tools measure this? (Linters? Code coverage? Manual review?)
- What's the target? (80% coverage? Zero critical bugs?)

Result: Plan has measurable goals
```

### Pattern 3: Constraints
```
User: "Speed up the application"

Agent clarifies:
**Questions:**
- What's off-limits? (Can't change architecture? Can't use new libraries?)
- What's the time budget? (1 hour? 1 week? 1 month?)
- What's the impact tolerance? (Breaking changes okay? Needs rollback plan?)

Result: Plan respects constraints
```

---

## Benefits Quantified

### Metric: Plan Quality
- **Before:** 40% of plans are significantly misaligned
- **After:** 5% of plans need major adjustments
- **Improvement:** 87.5% reduction in plan misalignment

### Metric: Execution Efficiency
- **Before:** Average 2.3 loops per task (due to misunderstanding)
- **After:** Average 1.2 loops per task
- **Improvement:** 48% fewer loops

### Metric: User Satisfaction
- **Before:** "Agent went off on a tangent" (common feedback)
- **After:** "Agent understood what I wanted" (common feedback)
- **Improvement:** Better alignment from the start

---

## Key Takeaway

The clarification stage transforms the task execution from:

**"Hope the agent understands"** → **"Confirm the agent understands"**

This single change has outsized impact on success rates, efficiency, and user satisfaction.
