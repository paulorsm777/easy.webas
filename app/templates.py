from typing import Dict, List, Optional
import json
import aiosqlite
from app.config import settings
from app.models import ScriptTemplate
import structlog

logger = structlog.get_logger()


class TemplateService:
    """Service for managing script templates"""

    def __init__(self):
        self.builtin_templates = {
            "google_search": {
                "description": "Busca no Google e retorna resultados",
                "category": "web_scraping",
                "script_content": """
async def main():
    await page.goto('https://google.com')
    await page.fill('input[name="q"]', 'playwright automation')
    await page.press('input[name="q"]', 'Enter')
    await page.wait_for_selector('.g')
    results = await page.query_selector_all('.g h3')
    return [await r.inner_text() for r in results[:5]]
""".strip()
            },
            "form_filling": {
                "description": "Preenche formulário e submete",
                "category": "automation",
                "script_content": """
async def main():
    await page.goto('https://httpbin.org/forms/post')
    await page.fill('input[name="custname"]', 'Test User')
    await page.fill('input[name="custtel"]', '123456789')
    await page.fill('input[name="custemail"]', 'test@example.com')
    await page.click('input[type="submit"]')
    await page.wait_for_load_state('networkidle')
    return await page.text_content('body')
""".strip()
            },
            "screenshot_capture": {
                "description": "Navega e captura informações da página",
                "category": "testing",
                "script_content": """
async def main():
    await page.goto('https://example.com')
    title = await page.title()
    content = await page.text_content('body')
    return {
        'title': title,
        'content_length': len(content),
        'url': page.url,
        'viewport': await page.viewport_size()
    }
""".strip()
            },
            "e_commerce_product_check": {
                "description": "Verifica informações de produto em site de e-commerce",
                "category": "monitoring",
                "script_content": """
async def main():
    # Example: Check product availability and price
    await page.goto('https://example-shop.com/product/123')

    # Wait for product information to load
    await page.wait_for_selector('.product-info')

    # Extract product details
    title = await page.text_content('.product-title')
    price = await page.text_content('.product-price')
    availability = await page.text_content('.product-availability')

    # Check if "Add to Cart" button is available
    add_to_cart = await page.query_selector('.add-to-cart:not([disabled])')
    in_stock = add_to_cart is not None

    return {
        'title': title,
        'price': price,
        'availability': availability,
        'in_stock': in_stock,
        'timestamp': datetime.now().isoformat()
    }
""".strip()
            },
            "social_media_post": {
                "description": "Extrai informações de post em rede social",
                "category": "social_monitoring",
                "script_content": """
async def main():
    # Example: Extract post information from social media
    await page.goto('https://example-social.com/post/123')

    # Wait for post to load
    await page.wait_for_selector('.post-content')

    # Extract post information
    author = await page.text_content('.post-author')
    content = await page.text_content('.post-content')
    likes = await page.text_content('.like-count')
    comments = await page.text_content('.comment-count')
    timestamp = await page.text_content('.post-timestamp')

    return {
        'author': author,
        'content': content,
        'likes': likes,
        'comments': comments,
        'timestamp': timestamp,
        'extracted_at': datetime.now().isoformat()
    }
""".strip()
            },
            "api_endpoint_test": {
                "description": "Testa endpoint de API através do navegador",
                "category": "api_testing",
                "script_content": """
async def main():
    # Test API endpoint through browser (useful for authentication flows)
    await page.goto('https://httpbin.org/json')

    # Get response content
    content = await page.text_content('pre')

    # Parse JSON response
    try:
        response_data = json.loads(content)
    except json.JSONDecodeError:
        response_data = {"error": "Invalid JSON response", "raw_content": content}

    # Additional checks
    status_check = await page.evaluate('''() => {
        return {
            status: window.performance.getEntriesByType('navigation')[0].responseStatus || 200,
            loadTime: window.performance.timing.loadEventEnd - window.performance.timing.navigationStart
        }
    }''')

    return {
        'response_data': response_data,
        'status': status_check['status'],
        'load_time_ms': status_check['loadTime'],
        'url': page.url,
        'timestamp': datetime.now().isoformat()
    }
""".strip()
            },
            "login_and_navigate": {
                "description": "Faz login e navega para página específica",
                "category": "authentication",
                "script_content": """
async def main():
    # Example login flow (customize for your needs)
    await page.goto('https://example.com/login')

    # Fill login form
    await page.fill('input[name="username"]', 'your_username')
    await page.fill('input[name="password"]', 'your_password')
    await page.click('button[type="submit"]')

    # Wait for login to complete
    await page.wait_for_url('**/dashboard*')  # Adjust URL pattern as needed

    # Navigate to specific page after login
    await page.goto('https://example.com/protected-page')
    await page.wait_for_load_state('networkidle')

    # Extract information from protected page
    title = await page.title()
    user_info = await page.text_content('.user-info')

    return {
        'title': title,
        'user_info': user_info,
        'login_successful': True,
        'current_url': page.url,
        'timestamp': datetime.now().isoformat()
    }
""".strip()
            },
            "data_table_extraction": {
                "description": "Extrai dados de tabela HTML",
                "category": "data_extraction",
                "script_content": """
async def main():
    await page.goto('https://example.com/data-table')

    # Wait for table to load
    await page.wait_for_selector('table')

    # Extract table headers
    headers = await page.evaluate('''() => {
        const headerCells = document.querySelectorAll('table thead th');
        return Array.from(headerCells).map(cell => cell.textContent.trim());
    }''')

    # Extract table rows
    rows = await page.evaluate('''() => {
        const dataRows = document.querySelectorAll('table tbody tr');
        return Array.from(dataRows).map(row => {
            const cells = row.querySelectorAll('td');
            return Array.from(cells).map(cell => cell.textContent.trim());
        });
    }''')

    # Structure data
    structured_data = []
    for row in rows:
        row_data = {}
        for i, header in enumerate(headers):
            if i < len(row):
                row_data[header] = row[i]
        structured_data.append(row_data)

    return {
        'headers': headers,
        'row_count': len(rows),
        'data': structured_data[:50],  # Limit to first 50 rows
        'total_columns': len(headers),
        'extracted_at': datetime.now().isoformat()
    }
""".strip()
            }
        }

    async def get_all_templates(self) -> List[ScriptTemplate]:
        """Get all available templates (builtin + custom)"""
        templates = []

        # Add builtin templates
        for name, template_data in self.builtin_templates.items():
            template = ScriptTemplate(
                name=name,
                description=template_data["description"],
                category=template_data["category"],
                script_content=template_data["script_content"],
                usage_count=0  # Builtin templates don't track usage
            )
            templates.append(template)

        # Add custom templates from database
        try:
            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                async with db.execute("""
                    SELECT name, description, script_content, category, usage_count
                    FROM script_templates
                    ORDER BY usage_count DESC, name
                """) as cursor:
                    rows = await cursor.fetchall()

                for row in rows:
                    template = ScriptTemplate(
                        name=row[0],
                        description=row[1] or "",
                        script_content=row[2],
                        category=row[3] or "custom",
                        usage_count=row[4] or 0
                    )
                    templates.append(template)

        except Exception as e:
            logger.error("Failed to load custom templates", error=str(e))

        return templates

    async def get_template_by_name(self, template_name: str) -> Optional[ScriptTemplate]:
        """Get specific template by name"""
        # Check builtin templates first
        if template_name in self.builtin_templates:
            template_data = self.builtin_templates[template_name]
            return ScriptTemplate(
                name=template_name,
                description=template_data["description"],
                category=template_data["category"],
                script_content=template_data["script_content"],
                usage_count=0
            )

        # Check custom templates in database
        try:
            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                async with db.execute("""
                    SELECT name, description, script_content, category, usage_count
                    FROM script_templates
                    WHERE name = ?
                """, (template_name,)) as cursor:
                    row = await cursor.fetchone()

                if row:
                    return ScriptTemplate(
                        name=row[0],
                        description=row[1] or "",
                        script_content=row[2],
                        category=row[3] or "custom",
                        usage_count=row[4] or 0
                    )

        except Exception as e:
            logger.error("Failed to load template", template_name=template_name, error=str(e))

        return None

    async def create_custom_template(self, name: str, description: str,
                                   script_content: str, category: str = "custom") -> bool:
        """Create a new custom template"""
        try:
            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                await db.execute("""
                    INSERT INTO script_templates (name, description, script_content, category)
                    VALUES (?, ?, ?, ?)
                """, (name, description, script_content, category))
                await db.commit()

            logger.info("Custom template created", template_name=name, category=category)
            return True

        except Exception as e:
            logger.error("Failed to create custom template", template_name=name, error=str(e))
            return False

    async def update_template_usage(self, template_name: str):
        """Increment usage count for a template"""
        if template_name in self.builtin_templates:
            # Builtin templates don't track usage in database
            return

        try:
            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                await db.execute("""
                    UPDATE script_templates
                    SET usage_count = usage_count + 1
                    WHERE name = ?
                """, (template_name,))
                await db.commit()

        except Exception as e:
            logger.error("Failed to update template usage", template_name=template_name, error=str(e))

    async def delete_custom_template(self, template_name: str) -> bool:
        """Delete a custom template (cannot delete builtin templates)"""
        if template_name in self.builtin_templates:
            return False  # Cannot delete builtin templates

        try:
            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                cursor = await db.execute("""
                    DELETE FROM script_templates WHERE name = ?
                """, (template_name,))
                await db.commit()

                if cursor.rowcount > 0:
                    logger.info("Custom template deleted", template_name=template_name)
                    return True

        except Exception as e:
            logger.error("Failed to delete custom template", template_name=template_name, error=str(e))

        return False

    async def get_templates_by_category(self, category: str) -> List[ScriptTemplate]:
        """Get templates filtered by category"""
        all_templates = await self.get_all_templates()
        return [t for t in all_templates if t.category.lower() == category.lower()]

    async def search_templates(self, query: str) -> List[ScriptTemplate]:
        """Search templates by name, description, or content"""
        all_templates = await self.get_all_templates()
        query_lower = query.lower()

        matching_templates = []
        for template in all_templates:
            if (query_lower in template.name.lower() or
                query_lower in template.description.lower() or
                query_lower in template.script_content.lower()):
                matching_templates.append(template)

        return matching_templates

    async def get_template_categories(self) -> List[Dict[str, any]]:
        """Get all available template categories with counts"""
        all_templates = await self.get_all_templates()
        categories = {}

        for template in all_templates:
            category = template.category
            if category not in categories:
                categories[category] = {
                    "name": category,
                    "count": 0,
                    "templates": []
                }
            categories[category]["count"] += 1
            categories[category]["templates"].append(template.name)

        return list(categories.values())

    async def validate_template_script(self, script_content: str) -> Dict[str, any]:
        """Validate template script content"""
        from app.validation import script_validator

        validation_result = script_validator.validate_script_for_execution(script_content)

        return {
            "is_valid": validation_result["is_safe"],
            "warnings": validation_result["analysis"].security_warnings,
            "estimated_time": validation_result["estimated_time"],
            "complexity": validation_result["analysis"].estimated_complexity,
            "detected_operations": validation_result["analysis"].detected_operations
        }


# Global template service instance
template_service = TemplateService()