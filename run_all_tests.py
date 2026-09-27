import asyncio
from playwright.async_api import async_playwright

prompts = [
    "delete all files from recycle bin",
    "open spotify on brave browser",
    "open notepad",
    'open gitbash and execute a command on gitbash - echo "hello vishwa"'
]

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to UI...")
        await page.goto("http://localhost:3000/")
        
        for i, prompt in enumerate(prompts):
            print(f"\n--- Testing Prompt {i+1} ---")
            print(f"Prompt: {prompt}")
            
            # Clear and fill the prompt
            await page.fill("input#prompt-input", prompt)
            
            print("Clicking Execute...")
            await page.click("button:has-text('Execute')")
            
            print("Waiting for SweetAlert...")
            # Wait for either the confirm button OR the dropdown
            confirm_btn = page.locator("button.swal2-confirm")
            dropdown = page.locator("select.swal2-select")
            
            # Wait until one is visible
            try:
                await confirm_btn.wait_for(state="visible", timeout=60000)
            except Exception as e:
                print("Error waiting for SweetAlert:", e)
                continue
                
            # If dropdown is visible, select Brave
            if await dropdown.is_visible():
                print("Selecting Brave...")
                await dropdown.select_option(value="Brave")
            
            print("Confirming Execution...")
            await confirm_btn.click()
            
            print("Waiting for Terminal Output...")
            output_box = page.locator("#powershell-output")
            await output_box.wait_for(state="visible", timeout=30000)
            
            text = await output_box.inner_text()
            print("Terminal Output:")
            print(text)
            
            # Reset UI for next test by reloading
            await page.reload()
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
