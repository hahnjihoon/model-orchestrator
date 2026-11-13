from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter()


@router.get("/", include_in_schema=False)
async def index():
    return RedirectResponse(url="/docs")


@router.get("/docs", include_in_schema=False)
async def docs(request: Request):
    html = get_swagger_ui_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} - Swagger UI",
        swagger_ui_parameters=request.app.swagger_ui_parameters,
    ).body.decode("utf-8")
    html = html.replace("<head>", '<head>\n<meta charset="utf-8">', 1)
    html = html.replace(
        "SwaggerUIBundle({",
        """SwaggerUIBundle({
        plugins: [function(system) {
            return {
                components: {
                    JsonSchema_string_multiline: function(props) {
                        return system.React.createElement("textarea", {
                            value: props.value == null ? "" : props.value,
                            disabled: props.disabled,
                            rows: 10,
                            style: {width: "100%", resize: "vertical"},
                            onChange: function(event) {
                                props.onChange(event.target.value, props.keyName);
                            }
                        });
                    }
                }
            };
        }],""",
        1,
    )
    return HTMLResponse(html)
