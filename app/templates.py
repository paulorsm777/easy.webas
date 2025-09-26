from typing import Dict, List, Optional
from .models import ScriptTemplate
from .database import db
from .logger import Logger

logger = Logger("templates")

# Built-in script templates
BUILT_IN_TEMPLATES = {
    "google_search": {
        "name": "google_search",
        "description": "Busca no Google e retorna os primeiros resultados",
        "category": "web_scraping",
        "script_content": '''
async def main():
    """
    Realiza uma busca no Google e retorna os primeiros 5 resultados
    """
    await page.goto('https://google.com')

    # Aceitar cookies se necessário
    try:
        accept_button = page.locator('button:has-text("Accept all"), button:has-text("I agree")')
        if await accept_button.count() > 0:
            await accept_button.first.click()
    except:
        pass

    # Buscar
    search_box = page.locator('input[name="q"], textarea[name="q"]')
    await search_box.fill('playwright automation')
    await search_box.press('Enter')

    # Aguardar resultados
    await page.wait_for_selector('.g', timeout=10000)

    # Extrair resultados
    results = []
    result_elements = page.locator('.g h3')
    count = await result_elements.count()

    for i in range(min(5, count)):
        try:
            title = await result_elements.nth(i).inner_text()
            results.append(title)
        except:
            continue

    return {
        'search_term': 'playwright automation',
        'results_count': len(results),
        'results': results,
        'page_title': await page.title()
    }
''',
    },
    "form_filling": {
        "name": "form_filling",
        "description": "Preenche um formulário de exemplo e submete",
        "category": "automation",
        "script_content": '''
async def main():
    """
    Preenche um formulário de teste no httpbin.org
    """
    await page.goto('https://httpbin.org/forms/post')

    # Preencher campos
    await page.fill('input[name="custname"]', 'João Silva')
    await page.fill('input[name="custtel"]', '11999887766')
    await page.fill('input[name="custemail"]', 'joao.silva@example.com')
    await page.fill('textarea[name="comments"]', 'Teste de automação com Playwright')

    # Selecionar tamanho
    await page.select_option('select[name="size"]', 'large')

    # Marcar topping
    await page.check('input[name="topping"][value="bacon"]')

    # Submeter formulário
    await page.click('input[type="submit"]')

    # Aguardar resposta
    await page.wait_for_load_state('networkidle')

    # Extrair resposta
    response_text = await page.text_content('body')

    return {
        'success': True,
        'form_data': {
            'name': 'João Silva',
            'phone': '11999887766',
            'email': 'joao.silva@example.com',
            'size': 'large',
            'topping': 'bacon'
        },
        'response_length': len(response_text),
        'current_url': page.url
    }
''',
    },
    "screenshot_capture": {
        "name": "screenshot_capture",
        "description": "Navega para uma página e captura informações detalhadas",
        "category": "testing",
        "script_content": '''
async def main():
    """
    Navega para example.com e coleta informações da página
    """
    await page.goto('https://example.com')

    # Aguardar carregamento completo
    await page.wait_for_load_state('networkidle')

    # Coletar informações básicas
    title = await page.title()
    url = page.url
    viewport = await page.viewport_size()

    # Contar elementos
    links_count = await page.locator('a').count()
    images_count = await page.locator('img').count()
    paragraphs_count = await page.locator('p').count()

    # Extrair texto principal
    main_content = await page.text_content('body')

    # Verificar se há formulários
    forms_count = await page.locator('form').count()

    # Coletar meta tags
    meta_description = await page.get_attribute('meta[name="description"]', 'content') or ''

    return {
        'page_info': {
            'title': title,
            'url': url,
            'viewport': viewport,
            'content_length': len(main_content.strip()) if main_content else 0
        },
        'elements': {
            'links': links_count,
            'images': images_count,
            'paragraphs': paragraphs_count,
            'forms': forms_count
        },
        'meta': {
            'description': meta_description
        },
        'sample_content': main_content[:200] + '...' if main_content and len(main_content) > 200 else main_content
    }
''',
    },
    "api_testing": {
        "name": "api_testing",
        "description": "Testa uma API REST usando o navegador",
        "category": "testing",
        "script_content": '''
async def main():
    """
    Testa a API do httpbin.org através do navegador
    """
    # Testar GET
    await page.goto('https://httpbin.org/json')

    # Extrair resposta JSON
    json_response = await page.text_content('pre')

    # Testar página de IP
    await page.goto('https://httpbin.org/ip')
    ip_response = await page.text_content('pre')

    # Testar user-agent
    await page.goto('https://httpbin.org/user-agent')
    ua_response = await page.text_content('pre')

    return {
        'tests': {
            'json_endpoint': {
                'url': 'https://httpbin.org/json',
                'response_length': len(json_response) if json_response else 0,
                'success': bool(json_response and 'slideshow' in json_response)
            },
            'ip_endpoint': {
                'url': 'https://httpbin.org/ip',
                'response_length': len(ip_response) if ip_response else 0,
                'success': bool(ip_response and 'origin' in ip_response)
            },
            'user_agent_endpoint': {
                'url': 'https://httpbin.org/user-agent',
                'response_length': len(ua_response) if ua_response else 0,
                'success': bool(ua_response and 'user-agent' in ua_response)
            }
        },
        'summary': {
            'total_tests': 3,
            'passed_tests': sum([
                bool(json_response and 'slideshow' in json_response),
                bool(ip_response and 'origin' in ip_response),
                bool(ua_response and 'user-agent' in ua_response)
            ])
        }
    }
''',
    },
    "ecommerce_demo": {
        "name": "ecommerce_demo",
        "description": "Demonstra navegação em site de e-commerce",
        "category": "automation",
        "script_content": '''
async def main():
    """
    Navega em um site de e-commerce de demonstração
    """
    await page.goto('https://demo.opencart.com/')

    # Aguardar carregamento
    await page.wait_for_load_state('networkidle')

    # Buscar por produto
    search_box = page.locator('input[name="search"]')
    await search_box.fill('laptop')
    await search_box.press('Enter')

    # Aguardar resultados
    await page.wait_for_selector('.product-thumb', timeout=10000)

    # Contar produtos encontrados
    products = page.locator('.product-thumb')
    product_count = await products.count()

    # Extrair informações dos primeiros 3 produtos
    product_list = []
    for i in range(min(3, product_count)):
        try:
            product = products.nth(i)
            name = await product.locator('.caption h4 a').inner_text()
            price = await product.locator('.price').inner_text()

            product_list.append({
                'name': name.strip(),
                'price': price.strip()
            })
        except:
            continue

    # Verificar categorias disponíveis
    categories = page.locator('.list-group-item')
    category_count = await categories.count()

    return {
        'search_term': 'laptop',
        'results': {
            'total_products': product_count,
            'products_sampled': len(product_list),
            'products': product_list
        },
        'site_info': {
            'title': await page.title(),
            'categories_count': category_count,
            'url': page.url
        }
    }
''',
    },
    "social_media_check": {
        "name": "social_media_check",
        "description": "Verifica links de redes sociais em uma página",
        "category": "web_scraping",
        "script_content": '''
async def main():
    """
    Analisa uma página em busca de links de redes sociais
    """
    await page.goto('https://github.com')

    # Aguardar carregamento
    await page.wait_for_load_state('networkidle')

    # Buscar links de redes sociais
    social_patterns = {
        'twitter': ['twitter.com', 't.co'],
        'facebook': ['facebook.com', 'fb.com'],
        'instagram': ['instagram.com'],
        'linkedin': ['linkedin.com'],
        'youtube': ['youtube.com', 'youtu.be'],
        'github': ['github.com']
    }

    all_links = await page.locator('a').all()
    social_links = {}

    for link in all_links:
        try:
            href = await link.get_attribute('href')
            if href:
                for platform, domains in social_patterns.items():
                    for domain in domains:
                        if domain in href:
                            if platform not in social_links:
                                social_links[platform] = []
                            social_links[platform].append(href)
                            break
        except:
            continue

    # Contar outros elementos
    images_count = await page.locator('img').count()
    buttons_count = await page.locator('button').count()
    forms_count = await page.locator('form').count()

    return {
        'page_analysis': {
            'title': await page.title(),
            'url': page.url,
            'total_links': len(all_links),
            'images': images_count,
            'buttons': buttons_count,
            'forms': forms_count
        },
        'social_media': {
            'platforms_found': list(social_links.keys()),
            'total_social_links': sum(len(links) for links in social_links.values()),
            'details': social_links
        }
    }
''',
    },
}


class TemplateManager:
    def __init__(self):
        self.templates_cache = {}

    async def initialize(self):
        """Initialize templates in database"""
        logger.info("template_manager_initializing")

        # Ensure built-in templates exist in database
        for template_data in BUILT_IN_TEMPLATES.values():
            await self._ensure_template_exists(template_data)

        logger.info(
            "template_manager_initialized", builtin_templates=len(BUILT_IN_TEMPLATES)
        )

    async def _ensure_template_exists(self, template_data: Dict):
        """Ensure a template exists in the database"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM script_templates WHERE name = ?",
                (template_data["name"],),
            )

            row = await cursor.fetchone()

            if not row:
                await conn.execute(
                    """
                    INSERT INTO script_templates (name, description, script_content, category)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        template_data["name"],
                        template_data["description"],
                        template_data["script_content"],
                        template_data["category"],
                    ),
                )
                await conn.commit()

                logger.info("template_created", name=template_data["name"])

    async def get_all_templates(self) -> List[ScriptTemplate]:
        """Get all available templates"""
        async with db.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT id, name, description, script_content, category, created_at, usage_count
                FROM script_templates
                ORDER BY category, name
            """)

            rows = await cursor.fetchall()
            templates = []

            for row in rows:
                templates.append(
                    ScriptTemplate(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        script_content=row["script_content"],
                        category=row["category"],
                        created_at=row["created_at"],
                        usage_count=row["usage_count"],
                    )
                )

            return templates

    async def get_template_by_name(self, name: str) -> Optional[ScriptTemplate]:
        """Get a specific template by name"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, description, script_content, category, created_at, usage_count
                FROM script_templates
                WHERE name = ?
            """,
                (name,),
            )

            row = await cursor.fetchone()

            if row:
                return ScriptTemplate(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    script_content=row["script_content"],
                    category=row["category"],
                    created_at=row["created_at"],
                    usage_count=row["usage_count"],
                )

            return None

    async def get_templates_by_category(self, category: str) -> List[ScriptTemplate]:
        """Get templates filtered by category"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, description, script_content, category, created_at, usage_count
                FROM script_templates
                WHERE category = ?
                ORDER BY name
            """,
                (category,),
            )

            rows = await cursor.fetchall()
            templates = []

            for row in rows:
                templates.append(
                    ScriptTemplate(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        script_content=row["script_content"],
                        category=row["category"],
                        created_at=row["created_at"],
                        usage_count=row["usage_count"],
                    )
                )

            return templates

    async def get_template_categories(self) -> List[str]:
        """Get all available categories"""
        async with db.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT DISTINCT category
                FROM script_templates
                ORDER BY category
            """)

            rows = await cursor.fetchall()
            return [row["category"] for row in rows if row["category"]]

    async def increment_template_usage(self, template_name: str):
        """Increment usage counter for a template"""
        async with db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE script_templates
                SET usage_count = usage_count + 1
                WHERE name = ?
            """,
                (template_name,),
            )
            await conn.commit()

            logger.info("template_usage_incremented", name=template_name)

    async def create_custom_template(self, template: ScriptTemplate) -> ScriptTemplate:
        """Create a new custom template"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO script_templates (name, description, script_content, category)
                VALUES (?, ?, ?, ?)
            """,
                (
                    template.name,
                    template.description,
                    template.script_content,
                    template.category,
                ),
            )

            template_id = cursor.lastrowid
            await conn.commit()

            logger.info(
                "custom_template_created",
                name=template.name,
                category=template.category,
            )

            return await self.get_template_by_id(template_id)

    async def get_template_by_id(self, template_id: int) -> Optional[ScriptTemplate]:
        """Get template by ID"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, description, script_content, category, created_at, usage_count
                FROM script_templates
                WHERE id = ?
            """,
                (template_id,),
            )

            row = await cursor.fetchone()

            if row:
                return ScriptTemplate(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    script_content=row["script_content"],
                    category=row["category"],
                    created_at=row["created_at"],
                    usage_count=row["usage_count"],
                )

            return None

    async def update_template(
        self, template_id: int, updates: Dict
    ) -> Optional[ScriptTemplate]:
        """Update an existing template"""
        update_fields = []
        update_values = []

        for field, value in updates.items():
            if field in ["name", "description", "script_content", "category"]:
                update_fields.append(f"{field} = ?")
                update_values.append(value)

        if not update_fields:
            return await self.get_template_by_id(template_id)

        update_values.append(template_id)

        async with db.get_connection() as conn:
            await conn.execute(
                f"UPDATE script_templates SET {', '.join(update_fields)} WHERE id = ?",
                update_values,
            )
            await conn.commit()

        logger.info("template_updated", template_id=template_id)
        return await self.get_template_by_id(template_id)

    async def delete_template(self, template_id: int) -> bool:
        """Delete a template"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM script_templates WHERE id = ?", (template_id,)
            )
            await conn.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("template_deleted", template_id=template_id)

            return deleted

    async def get_popular_templates(self, limit: int = 10) -> List[ScriptTemplate]:
        """Get most popular templates by usage"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, description, script_content, category, created_at, usage_count
                FROM script_templates
                WHERE usage_count > 0
                ORDER BY usage_count DESC
                LIMIT ?
            """,
                (limit,),
            )

            rows = await cursor.fetchall()
            templates = []

            for row in rows:
                templates.append(
                    ScriptTemplate(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        script_content=row["script_content"],
                        category=row["category"],
                        created_at=row["created_at"],
                        usage_count=row["usage_count"],
                    )
                )

            return templates


# Global template manager
template_manager = TemplateManager()
