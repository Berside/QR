import asyncio
import click
from PIL import Image
from ..nimmy.bluetooth import find_device
from ..nimmy.printer import PrinterClient, InfoEnum
from ..nimmy.logger_config import setup_logger, get_logger, logger_enable
from ..nimmy.helper import print_info, print_error, print_success

setup_logger()
logger = get_logger()


@click.group(context_settings={"help_option_names": ['-h', '--help']})
@click.option(
    "-v",
    "--verbose",
    count=True,
    default=0,
    help="Enable verbose logging",
)
@click.pass_context
def niimbot_cli(ctx, verbose):
    ctx.ensure_object(dict)
    ctx.obj['VERBOSE'] = verbose
    setup_logger()
    logger_enable(verbose)


@niimbot_cli.command("print")
@click.option(
    "-m",
    "--model",
    type=click.Choice(["b1", "b18", "b21", "b31", "d11", "d110"], False),
    # default="d110",
    default="d110",
    show_default=True,
    help="Niimbot printer model",
)
@click.option(
    "-d",
    "--density",
    type=click.IntRange(1, 5),
    default=3,
    show_default=True,
    help="Print density",
)
@click.option(
    "-n",
    "--quantity",
    type=click.IntRange(1, 65535),
    default=1,
    show_default=True,
    help="Print quantity",
)
@click.option(
    "--vo",
    "vertical_offset",
    default=0,
    show_default=True,
    help="Vertical offset in pixels",
)
@click.option(
    "--ho",
    "horizontal_offset",
    default=0,
    show_default=True,
    help="Horizontal offset in pixels",
)
@click.option(
    "-r",
    "--rotate",
    type=click.Choice(["0", "90", "180", "270"]),
    default="0",
    show_default=True,
    help="Image rotation (clockwise)",
)
@click.option(
    "-i",
    "--image",
    type=click.Path(exists=True),
    required=True,
    help="Image path",
)
def print_command(model, density, rotate, image, quantity, vertical_offset, horizontal_offset):
    logger.info(f"Niimbot Printing Start")

    model = model.lower()
    max_width_px = 600 if model == "b31" else (384 if model in ("b1", "b18", "b21") else 400)
    if model in ("b18", "d11", "d110") and density > 3:
        density = 3
    try:
        with Image.open(image) as source:
            image = source.copy()
        if rotate != "0":
            image = image.rotate(-int(rotate), expand=True)
        if image.width > max_width_px:
            raise ValueError(f"Image width too big for {model.upper()}: {image.width} > {max_width_px}")
        asyncio.run(_print(model, density, image, quantity, vertical_offset, horizontal_offset))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


async def _print(model, density, image, quantity, vertical_offset, horizontal_offset):
    print_info("Starting print job")
    device = await find_device(model)
    printer = PrinterClient(device)
    try:
        if not await printer.connect():
            raise RuntimeError("Cannot connect to printer")
        await printer.print_image(image, density=density, quantity=quantity,
                                  vertical_offset=vertical_offset, horizontal_offset=horizontal_offset)
        print_success("Print job completed")
    finally:
        await printer.disconnect()


@niimbot_cli.command("info")
@click.option(
    "-m",
    "--model",
    type=click.Choice(["b1", "b18", "b21", "b31", "d11", "d110"], False),
    default="d110",
    show_default=True,
    help="Niimbot printer model",
)
def info_command(model):
    logger.info("Niimbot Information")
    print_info("Niimbot Information")
    asyncio.run(_info(model))


async def _info(model):
    try:
        device = await find_device(model)
        printer = PrinterClient(device)
        await printer.connect()
        device_serial = await printer.get_info(InfoEnum.DEVICESERIAL)
        software_version = await printer.get_info(InfoEnum.SOFTVERSION)
        hardware_version = await printer.get_info(InfoEnum.HARDVERSION)
        print(f"Device Serial : {device_serial}")
        print(f"Software Version : {software_version}")
        print(f"Hardware Version : {hardware_version}")
        await printer.disconnect()
    except Exception as e:
        logger.debug(f"{e}")
        print_error(e)
        # await printer.disconnect()


cli = click.CommandCollection(sources=[niimbot_cli])
if __name__ == "__main__":
    niimbot_cli(obj={})
