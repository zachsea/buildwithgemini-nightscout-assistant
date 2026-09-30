# My agent: Nightscout Assistant
One-liner: A conversational health assistant that helps users understand and manage their diabetes by analyzing recent glucose and insulin data from their Nightscout instance, visualizing trends, and providing personalized insights.

Tool coverage:
- Memory: The user's Nightscout URL, access token, target glucose ranges, and preferred insight types (e.g., overnight trends).
- Tools: Fetch latest sensor glucose (SG) values, fetch recent treatments (insulin/carbs), and fetch device status from the Nightscout API.
- Catalog/UI: Custom interactive cards showing current glucose, trend arrows, time-in-range stats, and tables of recent treatments.
- Image gen: Motivational/celebratory badges for hitting goals, or visual representations of logged meals.
- Sandbox: Calculate complex statistics (estimated A1C, standard deviation, time-in-range for specific windows) from raw Nightscout JSON data.

Recommended for every project: memory, storage, tools, image generation, A2UI
Agent-specific / stretch (pick what fits): Code sandbox for advanced statistical calculations.
