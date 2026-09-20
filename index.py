







import requests
from firecrawl import Firecrawl
from playwright.async_api import async_playwright
from rate_limiter import rate_limiter
from pydantic import BaseModel, Field
from supabase import create_client, Client
import os
import json
from sitemap_urls import find_urls_from_sitemap
from google import genai
from google.genai import types
from dotenv import load_dotenv
from ollama import chat
import asyncio
import resend


load_dotenv()

app = Firecrawl(api_key="fc-f8a328f3c47e401797bb2ab892f8c6cd")
resend.api_key = os.getenv("RESEND_API_KEY")

client = genai.Client()


supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def send_new_vacancy_email(vacancy):
    
    from_email = os.getenv("RESEND_FROM_EMAIL")
    to_email = os.getenv("RESEND_TO_EMAIL")

    if not resend.api_key or not from_email or not to_email:
        raise ValueError("RESEND_API_KEY, RESEND_FROM_EMAIL, and RESEND_TO_EMAIL must be set.")

    email_subject = f"New VC internship found: {vacancy.job_title or 'Untitled role'}"
    email_html = f"""
    <h2>{vacancy.job_title or 'New VC internship found'}</h2>
    <p><strong>Company:</strong> {vacancy.company or 'Unknown'}</p>
    <p><strong>Location:</strong> {vacancy.job_location or 'Unknown'}</p>
    <p><strong>Description:</strong> {vacancy.job_description or 'No description found.'}</p>
    <p><strong>Application link:</strong> <a href="{vacancy.application_link or '#'}">{vacancy.application_link or 'No link found'}</a></p>
    """

    return resend.Emails.send({
        "from": from_email,
        "to": to_email,
        "subject": email_subject,
        "html": email_html,
    })




## may be cheaper to break down scraping of web-page, and returning data in structured output

## use rate-limiter, so free LLMs work fine enough

## pass both basic and js contents, if they both exist
class Vacancy(BaseModel):
    job_title: str | None = Field(
        description="The job title of the VC internship, if it exists"
    )
    application_link: str | None = Field(
        description="If a url link exists for the user to click through to apply, return the url link here"
    )
    job_description: str | None = Field(
            description="the description of the VC internship, if available"
    )
    job_location: str | None = Field(
        description="the location of the VC internship"
    )
    company: str | None = Field(
        description="The VC company the listing is for"
    )



def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def build_vacancy_instruction(basic_html, js_contents, max_chars = None):
    basic_text = basic_html or ""
    js_text = js_contents or ""

    if max_chars is not None:
        per_html_version = max(1, max_chars // 2)
        basic_text = basic_text[:per_html_version]
        js_text = js_text[:per_html_version]

    return f"""
            This is the contents of the plain html version of the url:
            {json.dumps(basic_text)}



            This is the contents of the JS loaded version of the url:
            {json.dumps(js_text)}

            """



def filter_job_opportunity_urls(url_list):
    job_keywords = [
        "work-with-us",
        "opportunity",
        "opportunities",
        "intern",
        "internship",
        "internships",
        "graduate",
        "talent",
        "vacancy",
        "vacancies",
        "apply",
        "application",
        "positions",
        "openings",
    ]

    return [
        url
        for url in url_list
        if any(keyword in url.lower() for keyword in job_keywords)
    ]

def update_url_list(parent_url, child_url, contains_listing: bool):


    with open("url_list_tracker.json", "r", encoding="utf-8") as file:
        try:
             contents = json.load(file)
        except:
            contents = {}
    
        exists = contents.get(parent_url, None)
        if not exists:
            contents[parent_url] = {}
        
        contents[parent_url][child_url] = contains_listing
        with open("url_list_tracker.json", "w", encoding="utf-8") as file_new:
                json.dump(contents, file_new, indent=2)


class ResponseSchema(BaseModel):
    is_vacancy_listing: bool = Field(
        ...,
        description="Does the html/page contents that has been passed to you contain a job listing for a Venture Capital internship?"
    )
    vacancy: Vacancy | None = Field(
        description="If a VC internship exists in the page data, then return the details as a Vacancy Pydantic schema specified"
    )
            


def check_if_empty(vc_url, url):

    with open("url_list_tracker.json", "r", encoding="utf-8") as file:
        try:
            contents = json.load(file)
        except:
            contents = {}
            return False
        
        main = contents.get(vc_url, None)
        if main is None:
            return False
        branch = main.get(url, None)
        if branch is None:
            return False
        else:
            if branch == False:
                return True
            else:
                return False


async def main():

    vc_list = []
    

    with open("vcs.json", "r", encoding="utf-8") as f:
        contents = json.load(f)
        vc_list.extend(contents)
    
    #vc_list = vc_list[:5]

    for index, vc_url in enumerate(vc_list):

        



        print(f"Starting VC company no. {index}: {vc_url} of {len(vc_list)}")

        url_list = find_urls_from_sitemap(vc_url)
        print(f"number of urls returned for {vc_url}: {len(url_list)}")
        url_list = filter_job_opportunity_urls(url_list)
        print(f"number of job/opportunity urls returned for {vc_url}: {len(url_list)}")
        
        if not url_list:
            continue
        
        for index1, url in enumerate(url_list):
            print(f"VC company no. {index}: {vc_url} no. {index1} of {len(url_list)}")

            ## for now, skip if already checked and empty
            empty = check_if_empty(vc_url, url)
            if empty:
                print("child url already checked on prior run - empty, so skipping.. ")
                continue
            
            try:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0"
                    },
                    timeout=30,
                )
        
                response.raise_for_status()
                basic_html = response.text
            except requests.RequestException as e:
                print(f"Requests failed for {url}: {e}")
                update_url_list(vc_url, url, False)
                continue

            ## get anything behind JS
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    html = await page.content()
                    js_contents = html
                except Exception as e:
                    print(f"Playwright failed for {url}: {e}")
                    js_contents = ""
                finally:
                    await browser.close()
        

        
        
            user_instruction = build_vacancy_instruction(basic_html, js_contents)

            system_instruction = """
            You need to check if a VC internship role/job listing exists in the contents of a URL that you are provided with (both html and js versions).

            If so, return the structured output schema specified with as many fields completed as possible from the info.

            ** Rules **
            - VC internships only - not permanent jobs or any other kinds of jobs.

            """
            
            tokens_for_call = estimate_tokens(system_instruction + user_instruction)
            token_resize_attempts = 0
            skip_url = False
            while True:
                limiter_result = await rate_limiter(tokens_for_call)

                if not limiter_result["trim_tokens"]:
                    break
        
                print(f"Original LLM call was over token limit - editing url page token content to fit..")
                print(f"Amount to trim: {limiter_result['amount_to_trim']}")
                max_chars = max(1_000, (tokens_for_call - limiter_result["amount_to_trim"]) * 4)
                print(f"max_chars should be: {max_chars}")
                user_instruction = build_vacancy_instruction(basic_html, js_contents, max_chars=max_chars)
                tokens_for_call = estimate_tokens(system_instruction + user_instruction)
                token_resize_attempts += 1
                if token_resize_attempts >= 3:
                    print(".. Token_resize attempts has hit limit of 3 - will skip this URL and move to next one.. ")
                    skip_url = True
                    break
            
            if skip_url:
                update_url_list(vc_url, url, False)
                continue

            
            ollamaResponse = chat(
                model="gemma4:e4b",
                messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": user_instruction }],
                format=ResponseSchema.model_json_schema()
            )

            parsed = ResponseSchema.model_validate_json(ollamaResponse.message.content)
            
            #response = client.models.generate_content(
                #model="gemini-2.5-flash-lite",
                #contents=user_instruction,
               # config=types.GenerateContentConfig(
                   # system_instruction=system_instruction,
                   # response_mime_type="application/json",
                   # response_schema=ResponseSchema
                #) 
            #)

            response_parsed = parsed #response.parsed
            print(f"VC company no. {index}: {vc_url} of {len(vc_list)}: {response_parsed.model_dump_json()}")

            if not response_parsed.is_vacancy_listing or not response_parsed.vacancy or not response_parsed.vacancy.company:
                print("Not a VC internship - skipping..")
                update_url_list(vc_url, url, False)
                continue ## skip to next vc_url, as not vacancy listing exist

            ## retrieve from supabase table to see if the same listing already exists:
            update_url_list(vc_url, url, True)
            response = supabase.table("vc_internship_roles").select("*").eq("company", response_parsed.vacancy.company.strip("")).execute()
            ## filter by company name, to make results managable
            if not response or response.count == None:
                continue
            
            ## LLM call to check whether the role is already in the data
            user_prompt = f"""There are the roles already stored for Venture Capital Internships
            {json.dumps(response.data)}
            """

            system_instruction = """You need to determine whether a new Venture Capital internship position scraped from a company's website
            already exists in the data of VC internships from my database - if it already exists, i don't need to add it to the database.

            Return your response to match the pydantic structured output schema
            
            """

            class AlreadyExists(BaseModel):
                already_exists: bool = Field(
                    ...,
                    description="does the VC internship position already exist?"
                )
                reasoning: str = Field(
                    ...,
                    description="the evidence behind your judgement of whether the VC internship position already exists in the data from my database"
                )
            
            tokens_for_call = estimate_tokens(system_instruction + user_prompt)
            token_resize_attempts = 0
            skip_url = False
            while True:
                limiter_result = await rate_limiter(tokens_for_call)

                if not limiter_result["trim_tokens"]:
                    break
        
                print(f"Original LLM call was over token limit - editing url page token content to fit..")
                max_chars = max(1_000, (tokens_for_call - limiter_result["amount_to_trim"]) * 4)
                tokens_for_call = estimate_tokens(system_instruction + user_prompt)
                token_resize_attempts += 1

                if token_resize_attempts >= 3:
                    skip_url = True
                    break
            
            if skip_url:
                update_url_list(vc_url, url, False)
                print(".. Token_resize attempts has hit limit of 3 - will skip this URL and move to next one.. ")
                continue

           # response = client.models.generate_content(
               # model="gemini-2.5-flash-lite",
               # contents=user_prompt,
                #config=types.GenerateContentConfig(
                 #   system_instruction=system_instruction,
                #    response_mime_type="application/json",
                #    response_schema=AlreadyExists
               # )
            #)

            ollamaResponse = chat(
                model="gemma4:e4b",
                messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": user_prompt }],
                format=AlreadyExists.model_json_schema(),
                think=False
            )

            parsed = AlreadyExists.model_validate_json(ollamaResponse.message.content)

            already_exists_parsed = parsed #response.parsed
            if already_exists_parsed.already_exists is True:
                print(already_exists_parsed.reasoning)
                continue ## skip to next one
            
            ## else, insert to database
            # insert the Vacancy class instance of the original response_parsed
            response = supabase.table("vc_internship_roles").insert(response_parsed.vacancy.model_dump()).execute()
            print(response)

            ## then use resend to email any new ones
            send_new_vacancy_email(response_parsed.vacancy)




asyncio.run(main())


## virtual environment




