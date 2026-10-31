import asyncio
import os
import sys
from pathlib import Path
from unittest import result
import mcp

import certifi
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq



# Environment configuration
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATION_STACK_API_KEY = os.getenv("AVIATION_STACK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


PROJECT_DIR = Path(__file__).resolve().parent
WEATHER_SERVER_PATH = PROJECT_DIR / "custom_weather_mcp_server.py"


# local stdio MCP servers.
AVIATION_ENV = os.environ.copy()
AVIATION_ENV["AVIATION_STACK_API_KEY"] = AVIATION_STACK_API_KEY or ""

WEATHER_ENV = os.environ.copy()
WEATHER_ENV["OPENWEATHER_API_KEY"] = (OPENWEATHER_API_KEY or "")
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=GROQ_API_KEY
)

client= MultiServerMCPClient(
    {
        "tavily":{
            "transport":"http",
            "url":(
                "https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
                f"?tavily_api_key={TAVILY_API_KEY}"
            )
        },
        "aviationstack":{
            "transport": "stdio",
            "command":"uvx",
            "args":[
                "aviationstack-mcp",
            ],
            "env":AVIATION_ENV
        },
        "weather":{
            "transport": "stdio",
            "command":sys.executable, ## Use the same Python environment that runs app.py.
            "args":[str(WEATHER_SERVER_PATH)],
            "env":WEATHER_ENV
        }
    }
)

# Diagnostic function
async def get_all_tools():
    all_tools=[]
    
    for server_name in("tavily",'aviationstack',"weather"):
        try:
            tools = await client.get_tools(server_name = server_name)
            all_tools.extend(tools)
            print(
                f"\nAvailable tools from "
                f"{server_name} MCP:\n"
            )
            
            for tool in tools:
                print(tool.name)
        except Exception as e:
            print(
                f"\nCould not connect to "
                f"{server_name} MCP:\n{os.error}\n"
            )

# Tavily MCP tool

search_tool = None
async def initialize_mcp():
    global search_tool
    if search_tool is not None:
        return
    tools = await client.get_tools(server_name="tavily")
    tools_by_name = {
        tool.name: tool
        for tool in tools
    }
    search_tool = tools_by_name.get("tavily_search")
    
    if search_tool is None:
        available_tool = ", ".join(tools_by_name.keys())
        raise RuntimeError(
            "Tavily MCP connected, but the"
            "tavily_search tool was not found. "
            f"Available tools: {available_tool or None}"
        )

async def tavily_mcp_search(query: str):
    await initialize_mcp()
    result = await search_tool.ainvoke(
        {
            "query": query
        }
    )
    return result

# AviationStack MCP tools

aviation_tools = {}

async def initialize_aviation_tools():
    global aviation_tools
    if aviation_tools:
        return
    tools = await client.get_tools(server_name="aviationstack")
    aviation_tools = {
        tool.name: tool
        for tool in tools
    }
    if not aviation_tools:
        raise RuntimeError(
            "AviationStack MCP connected but"
            "returned no tools."
        )
async def aviation_mcp_call(
    tool_name: str,
    tool_args:dict =None
):
    await initialize_aviation_tools()
    tool = aviation_tools.get(tool_name)
    if tool is None:
        available_tool = ", ".join(sorted(aviation_tools.keys()))
        raise ValueError(
            f"AviationStack tool '{tool_name}'"
            "was not found. "
            f"Available tools: {available_tool or None}"
        )
    result = await tool.ainvoke(
        tool_args or {}
    )
    return result
        
    
# Weather MCP tools
weather_tool = None
forecast_tool =None

async def initialize_weather_tools():
    global weather_tool
    global forecast_tool
    
    if weather_tool is not None and forecast_tool is not None:
        return
    if not WEATHER_SERVER_PATH.exists():
        raise RuntimeError(
            f"Weather MCP server script not found at "
            f"{WEATHER_SERVER_PATH}. Please ensure the "
            "custom_weather_mcp_server.py file is present."
        )
    # Load only Weather.
    tools = await client.get_tools(server_name="weather")
    tools_by_name = {
        tool.name:tool
        for tool in tools
    }
    weather_tool = tools_by_name.get("get_current_weather")
    forecast_tool = tools_by_name.get("get_forecast")
    
    missing_tool = []
    if weather_tool is None:
        missing_tool.append("get_current_weather")
    if forecast_tool is None:
        missing_tool.append("get_forecast")
    if missing_tool:
        available_tool = ", ".join(tools_by_name.keys())
        raise RuntimeError(
            "Weather MCP connected, but the following tools were not found: "
            f"{', '.join(missing_tool)}. "
            f"Available tools: {available_tool or None}"
        )
    
async def weather_mcp_search(city: str):
    await initialize_weather_tools()
    result = await weather_tool.ainvoke(
        {
            "city": city
        }
    )
    return result

async def forecast_mcp_search(city: str):
    await initialize_weather_tools()
    result = await forecast_tool.ainvoke(
        {
            "city": city
        }
    )
    return result

# Destination extractor
def extract_destination(query: str):
    prompt = f""" 
    Extract only the destination city or country.
    Query:
    {query}
    
    Return only the destination name.
    """
    response = llm.invoke(prompt)
    return response.content.strip()

# if __name__ == "__main__":
#     asyncio.run(get_all_tools())