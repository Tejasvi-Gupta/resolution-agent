import json
import os
import uuid
from typing import Any, Callable
from google import genai
from google.genai import types

# =====================================================================
# MOCK DATABASES (Simulated Production State)
# =====================================================================

ORDERS_DB: dict[str, dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_name": "Aarav Sharma",
        "customer_email": "aarav.sharma@example.com",
        "item_id": "SKU-WH-900",
        "item_name": "Noise-Canceling Wireless Headphones",
        "amount_paid": 199.99,
        "order_status": "Delivered",
        "exchange_eligible": True,
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_name": "Priya Patel",
        "customer_email": "priya.patel@example.com",
        "item_id": "SKU-KB-450",
        "item_name": "Mechanical Tactile Keyboard (Limited Edition)",
        "amount_paid": 149.50,
        "order_status": "Delivered",
        "exchange_eligible": True,
    },
}

INVENTORY_DB: dict[str, dict[str, Any]] = {
    "SKU-WH-900": {
        "item_id": "SKU-WH-900",
        "item_name": "Noise-Canceling Wireless Headphones",
        "stock_count": 14,
    },
    "SKU-KB-450": {
        "item_id": "SKU-KB-450",
        "item_name": "Mechanical Tactile Keyboard (Limited Edition)",
        "stock_count": 0,  # Out of stock -> triggers automatic refund path
    },
}

REFUND_LEDGER: list[dict[str, Any]] = []
SENT_EMAILS: list[dict[str, Any]] = []


# =====================================================================
# STEP 1: FUNCTIONAL TOOLS (Deterministic & Structured)
# =====================================================================

def lookup_order(order_id: str) -> dict[str, Any]:
    """Retrieves order details, customer identity, and exchange eligibility."""
    order = ORDERS_DB.get(order_id.strip().upper())
    if not order:
        return {
            "status": "error",
            "error_code": "ORDER_NOT_FOUND",
            "message": f"No order record found for identifier '{order_id}'. Ask the customer to verify their order ID.",
        }
    return {
        "status": "success",
        "order": order,
    }


def check_inventory(item_id: str) -> dict[str, Any]:
    """Returns real-time warehouse stock counts and replacement availability."""
    item = INVENTORY_DB.get(item_id.strip().upper())
    if not item:
        return {
            "status": "error",
            "error_code": "ITEM_NOT_FOUND",
            "message": f"Item '{item_id}' does not exist in the warehouse catalog.",
        }
    stock = item["stock_count"]
    return {
        "status": "success",
        "item_id": item["item_id"],
        "item_name": item["item_name"],
        "stock_count": stock,
        "in_stock": stock > 0,
    }


def process_refund(order_id: str, reason: str) -> dict[str, Any]:
    """Issues a financial refund to the original payment method and logs a reference."""
    normalized_id = order_id.strip().upper()
    order = ORDERS_DB.get(normalized_id)
    if not order:
        return {
            "status": "error",
            "error_code": "ORDER_NOT_FOUND",
            "message": f"Cannot process refund: order '{order_id}' does not exist.",
        }

    if order.get("order_status") == "Refunded":
        return {
            "status": "error",
            "error_code": "ALREADY_REFUNDED",
            "message": f"Order '{normalized_id}' has already been refunded.",
        }

    refund_ref = f"REF-{uuid.uuid4().hex[:8].upper()}"
    amount = order["amount_paid"]
    order["order_status"] = "Refunded"

    record = {
        "refund_reference": refund_ref,
        "order_id": normalized_id,
        "amount_refunded": amount,
        "reason": reason,
    }
    REFUND_LEDGER.append(record)

    return {
        "status": "success",
        "refund_reference": refund_ref,
        "order_id": normalized_id,
        "amount_refunded": amount,
        "currency": "USD",
        "reason": reason,
    }


def send_customer_notification(email: str, message_body: str) -> dict[str, Any]:
    """Dispatches an official resolution confirmation email to the customer."""
    if "@" not in email:
        return {
            "status": "error",
            "error_code": "INVALID_EMAIL",
            "message": f"Invalid email address provided: '{email}'.",
        }

    notification = {
        "notification_id": f"MSG-{uuid.uuid4().hex[:6].upper()}",
        "recipient": email,
        "message_body": message_body,
    }
    SENT_EMAILS.append(notification)

    return {
        "status": "success",
        "notification_id": notification["notification_id"],
        "recipient": email,
        "delivery_status": "SENT",
    }


# =====================================================================
# STEP 2: DECLARATIVE TOOL CONTRACTS (Schemas)
# =====================================================================

TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="lookup_order",
            description=(
                "Look up an order in the database using its order ID to retrieve the customer's "
                "name, email, purchased item ID, order status, amount paid, and exchange eligibility."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "order_id": types.Schema(
                        type=types.Type.STRING,
                        description="The unique order identifier (e.g., 'ORD-1001').",
                    ),
                },
                required=["order_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="check_inventory",
            description=(
                "Check real-time warehouse stock counts for a specific item ID to determine "
                "whether a replacement unit is available for an exchange."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "item_id": types.Schema(
                        type=types.Type.STRING,
                        description="The warehouse SKU/item identifier (e.g., 'SKU-WH-900').",
                    ),
                },
                required=["item_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="process_refund",
            description=(
                "Issue a financial refund to the customer's original payment method. "
                "ONLY invoke this tool when the replacement item is out of stock (stock_count == 0) "
                "or when the order is marked ineligible for exchange."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "order_id": types.Schema(
                        type=types.Type.STRING,
                        description="The unique order identifier being refunded.",
                    ),
                    "reason": types.Schema(
                        type=types.Type.STRING,
                        description="Clear explanation for the refund (e.g., 'Damaged item; replacement out of stock').",
                    ),
                },
                required=["order_id", "reason"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_customer_notification",
            description=(
                "Send an official confirmation email summarizing the completed resolution "
                "(either exchange confirmation or refund reference details) to the customer."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "email": types.Schema(
                        type=types.Type.STRING,
                        description="The customer's email address retrieved from the order record.",
                    ),
                    "message_body": types.Schema(
                        type=types.Type.STRING,
                        description="The complete, polite confirmation message detailing the resolution.",
                    ),
                },
                required=["email", "message_body"],
            ),
        ),
    ]
)


# =====================================================================
# STEP 3 & STEP 5: REGISTRY WHITELIST, ARGUMENT VALIDATION & SAFE DISPATCH
# =====================================================================

TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "lookup_order": lookup_order,
    "check_inventory": check_inventory,
    "process_refund": process_refund,
    "send_customer_notification": send_customer_notification,
}

TOOL_REQUIRED_ARGS: dict[str, dict[str, type]] = {
    "lookup_order": {"order_id": str},
    "check_inventory": {"item_id": str},
    "process_refund": {"order_id": str, "reason": str},
    "send_customer_notification": {"email": str, "message_body": str},
}


def safe_dispatch(tool_name: str, raw_args: Any) -> dict[str, Any]:
    """
    Gatekeeper that enforces tool whitelisting, parses/validates arguments,
    and executes authorized functions safely.
    """
    # 1. Authorization Check (Whitelist)
    if tool_name not in TOOL_REGISTRY:
        return {
            "status": "error",
            "error_code": "UNAUTHORIZED_TOOL",
            "message": f"Tool '{tool_name}' is not registered or authorized for execution.",
        }

    # 2. Argument Parsing & Schema Validation
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            return {
                "status": "error",
                "error_code": "MALFORMED_ARGUMENTS",
                "message": f"Invalid JSON arguments: {exc}. Please provide valid JSON object parameters.",
            }
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT_TYPE",
            "message": "Tool arguments must be a dictionary of key-value pairs.",
        }

    expected_schema = TOOL_REQUIRED_ARGS[tool_name]
    for param_name, expected_type in expected_schema.items():
        if param_name not in args or args[param_name] is None:
            return {
                "status": "error",
                "error_code": "MISSING_REQUIRED_PARAMETER",
                "message": f"Missing required parameter '{param_name}' for tool '{tool_name}'.",
            }
        if not isinstance(args[param_name], expected_type):
            return {
                "status": "error",
                "error_code": "TYPE_MISMATCH",
                "message": (
                    f"Parameter '{param_name}' must be of type {expected_type.__name__}, "
                    f"got {type(args[param_name]).__name__}."
                ),
            }

    # 3. Deterministic Execution with Exception Containment
    try:
        target_fn = TOOL_REGISTRY[tool_name]
        filtered_args = {k: args[k] for k in expected_schema}
        return target_fn(**filtered_args)
    except Exception as exc:
        return {
            "status": "error",
            "error_code": "EXECUTION_FAILURE",
            "message": f"Unexpected tool failure in '{tool_name}': {str(exc)}",
        }


# =====================================================================
# STEP 4 & STEP 5: AGENTIC REACT LOOP WITH EXECUTION CEILING
# =====================================================================

SYSTEM_INSTRUCTION = """
You are an autonomous Customer Order Resolution Specialist.
Follow this strict decision workflow whenever a customer reports a damaged or defective item:

1. INVESTIGATE ORDER: Always call `lookup_order` first to verify the order details, customer email, item ID, and exchange eligibility.
   - If the order is not found, stop immediately and politely ask the customer to verify their order ID.
2. CHECK INVENTORY: If the order exists and is eligible for exchange, call `check_inventory` using the order's `item_id`.
3. DECIDE RESOLUTION:
   - IF `exchange_eligible` is True AND `stock_count` > 0: Approve a replacement exchange (do NOT issue a refund).
   - IF `stock_count` == 0 OR `exchange_eligible` is False: Automatically call `process_refund` with the order ID and a clear reason.
4. NOTIFY CUSTOMER: Once the exchange is confirmed or the refund is processed, call `send_customer_notification` using the customer's email from the order record.
5. FINAL RESPONSE: Conclude with a clear, polite summary of all actions taken (including refund reference numbers if applicable).
""".strip()


def run_resolution_agent(user_prompt: str, max_iterations: int = 5) -> dict[str, Any]:
    """
    Executes the bounded ReAct cycle until a final customer response is produced
    or the max_iterations ceiling is reached.
    """
    client = genai.Client()

    # Step 4.1: State Initialization
    conversation_history: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_prompt)],
        )
    ]

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"\n[ReAct Cycle — Iteration {iteration}/{max_iterations}]")

        # Step 4.2: Model Invocation with Tools
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=conversation_history,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[TOOL_DECLARATIONS],
                temperature=0.0,
            ),
        )

        candidate_content = response.candidates[0].content
        conversation_history.append(candidate_content)

        # Step 4.3: Tool Call Detection
        if not response.function_calls:
            print("  -> Final text response generated. Exiting loop.")
            return {
                "status": "completed",
                "iterations_used": iteration,
                "final_response": response.text,
            }

        # Step 4.4: Execution and State Feedback
        tool_response_parts: list[types.Part] = []
        for tool_call in response.function_calls:
            fn_name = tool_call.name
            fn_args = dict(tool_call.args) if tool_call.args else {}
            print(f"  -> Tool Call Requested: {fn_name}({fn_args})")

            result = safe_dispatch(fn_name, fn_args)
            print(f"  <- Tool Result: {json.dumps(result)}")

            tool_response_parts.append(
                types.Part.from_function_response(
                    name=fn_name,
                    response=result,
                )
            )

        # Append tool execution results back into state for Step 4.5 (Cycle Continuation)
        conversation_history.append(
            types.Content(role="user", parts=tool_response_parts)
        )

    # Step 5.1: Execution Ceiling Escalation
    print("\n[Guardrail Triggered] Max iterations reached. Escalating to human agent.")
    return {
        "status": "escalated",
        "iterations_used": iteration,
        "final_response": (
            "We are currently reviewing your request with a senior support specialist "
            "and will follow up shortly."
        ),
    }


# =====================================================================
# ACCEPTANCE CRITERIA VERIFICATION HARNESS
# =====================================================================

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        raise EnvironmentError("Please set the GEMINI_API_KEY environment variable first.")

    test_scenarios = [
        (
            "Scenario 1: In-Stock Item -> Replacement Exchange",
            "Hi, my headphones from order ORD-1001 arrived with a cracked headband. Can you help?",
        ),
        (
            "Scenario 2: Out-of-Stock Item -> Automatic Refund",
            "Hello, the keys on my keyboard from order ORD-1002 are broken out of the box.",
        ),
        (
            "Scenario 3: Invalid Order ID -> Graceful Recovery",
            "I received a damaged monitor under order ORD-9999 and need a replacement.",
        ),
    ]

    for title, customer_message in test_scenarios:
        print("=" * 72)
        print(title)
        print(f"Customer: {customer_message}")
        print("=" * 72)

        outcome = run_resolution_agent(customer_message, max_iterations=5)
        print(f"\nOutcome Status: {outcome['status']} (Iterations: {outcome['iterations_used']})")
        print(f"Agent Reply:\n{outcome['final_response']}\n")