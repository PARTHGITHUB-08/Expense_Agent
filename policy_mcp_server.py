import json
import logging
from mcp.server.fastmcp import FastMCP

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("policy_mcp_server")

# Initialize FastMCP server
mcp = FastMCP("Company Policy Server")

@mcp.tool()
def get_expense_policy(category: str) -> str:
    """Fetch the company policy limit and rules for a given expense category."""
    policies = {
        "flight": "Max $500 per domestic flight, $1500 international. Must book 14 days in advance.",
        "travel": "Max $500 per domestic flight, $1500 international. Must book 14 days in advance.",
        "meal": "Max $75 per day. No alcohol allowed on business expenses.",
        "food": "Max $75 per day. No alcohol allowed on business expenses.",
        "software": "Max $100 per month. Requires IT pre-approval via service desk.",
        "hardware": "Max $2000 per laptop. Replaced every 3 years. Keyboards/mice max $150.",
        "training": "Max $5000 per year per employee for approved courses."
    }
    
    cat_lower = category.lower()
    for key, policy in policies.items():
        if key in cat_lower:
            logger.info(f"Policy hit for {category}: {policy}")
            return f"Policy for '{category}': {policy}"
            
    default_policy = "Default Policy: Max $100 total. Any expense above this requires explicit manager approval."
    logger.info(f"No specific policy found for {category}. Using default.")
    return default_policy

if __name__ == "__main__":
    logger.info("Starting Policy MCP Server...")
    # Use stdio transport by default when run as a script
    mcp.run()
