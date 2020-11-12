class PricingCalculator(object):
    """This is a calculator for estimating S3 monthly costs.
    Currently supports S3 Standard Storage tiered"""

    @staticmethod
    def float_to_usd(f):
        """"Convert float f to USD string"""
        return '${:,.2f}'.format(f)

    @staticmethod
    def x_of_unit_to_bytes(x, unit):
        """Takes float x and unit KiB/MiB/GiB/TiB, and returns float of bytes in x of unit"""
        return x * PricingCalculator.unit_to_bytes(unit)

    @staticmethod
    def unit_to_bytes(unit):
        """Takes unit KiB/MiB/GiB/TiB and returns number of bytes in that unit"""
        return {
            'KiB': float(2 ** 10),  # 1 KiB = 1024 Bytes
            'MiB': float(2 ** 20),  # 1 MiB = 1,048,576 Bytes
            'GiB': float(2 ** 30),  # 1 GiB = 1,073,741,824 Bytes
            'TiB': float(2 ** 40)   # 1 TiB = 1,099,511,627,776 Bytes
        }[unit]

    @staticmethod
    def bytes_to_unit(x, unit):
        """Takes number of bytes x and unit KiB/MiB/GiB/TiB and returns x in that unit"""
        return x / PricingCalculator.unit_to_bytes(unit)

    @staticmethod
    def pricing():
        """ Returns dictionary of 3 tier pricing for standard S3 storage
            TODO load via boto3 https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pricing.html
            TODO return pricing info for more storage schemes and other services
        """
        return {
            'standard_tier_1': {
                'size': 50.0,  # in TiB
                'cost': 0.023  # per GiB
            },
            'standard_tier_2': {
                'size': 450.0,  # in TiB
                'cost': 0.022   # per GiB
            },
            'standard_tier_3': {
                'size': 500.0,  # in TiB
                'cost': 0.021   # per GiB
            }
        }

    @staticmethod
    def max_size_tier_1():
        """Returns the size in bytes of tier 1 standard s3 storage if it is maxed out"""
        return PricingCalculator.x_of_unit_to_bytes(PricingCalculator.pricing()['standard_tier_1']['size'], 'TiB')

    @staticmethod
    def max_size_tier_2():
        """Returns the size in bytes of tier 2 standard s3 storage if it is maxed out"""
        return PricingCalculator.x_of_unit_to_bytes(PricingCalculator.pricing()['standard_tier_2']['size'], 'TiB')

    @staticmethod
    def min_size_tier_3():
        """Returns the min size required to incur tier 3 standard s3 storage costs"""
        return PricingCalculator.x_of_unit_to_bytes(PricingCalculator.pricing()['standard_tier_3']['size'], 'TiB')

    @staticmethod
    def bytes_to_price_for_tier(b, t):
        """ Takes a number of bytes b and a tier name t and returns
            the cost of storing b bytes in tier t, returned as a float"""
        return PricingCalculator.bytes_to_unit(b, 'GiB') * PricingCalculator.pricing()[t]['cost']

    @staticmethod
    def max_cost_tier_1():
        """ Returns the cost of tier 1 standard s3 storage if it is maxed out"""
        return PricingCalculator.bytes_to_price_for_tier(PricingCalculator.max_size_tier_1(), 'standard_tier_1')

    @staticmethod
    def max_cost_tier_2():
        """ Returns the cost of tier 2 standard s3 storage if it is maxed out"""
        return PricingCalculator.bytes_to_price_for_tier(PricingCalculator.max_size_tier_2(), 'standard_tier_2')

    @staticmethod
    def bytes_to_cost_tier_1(b):
        """ Takes a number of bytes b and returns a float of cost in USD
            for bytes stored in tier 1 standard s3 storage"""
        return PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_1')

    @staticmethod
    def bytes_to_cost_tier_2(b):
        """ Takes a number of bytes b and returns a float of cost in USD
            for bytes stored in tier 2 standard s3 storage"""
        return PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_2')

    @staticmethod
    def bytes_to_cost_tier_3(b):
        """ Takes a number of bytes b and returns a float of cost in USD
            for bytes stored in tier 3 standard s3 storage"""
        return PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_3')

    @staticmethod
    def resolve_maxed_tier_1(b, p):
        """ Takes in floats of bytes b and price p, and accounts for a maxed out usage of Tier 1 storage,
            removing from bytes and adding to price."""
        b = b - PricingCalculator.max_size_tier_1()
        p = p + PricingCalculator.max_cost_tier_1()
        return b, p

    @staticmethod
    def resolve_maxed_tier_2(b, p):
        """ Takes in floats of bytes b and price p, and accounts for a maxed out usage of Tier 1 and 2 storage,
            removing from bytes and adding to price."""
        b, p = PricingCalculator.resolve_maxed_tier_1(b, p)
        b = b - PricingCalculator.max_size_tier_2()
        p = p + PricingCalculator.max_cost_tier_2()
        return b, p

    @staticmethod
    def bytes_to_price(b):
        """Takes in number of bytes b and returns price string in USD"""
        p = 0  # Price in USD, to be converted to price format at end

        if b <= PricingCalculator.max_size_tier_1():
            p = PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_1')
        elif b <= PricingCalculator.max_size_tier_2():
            b, p = PricingCalculator.resolve_maxed_tier_1(b, p)
            p += PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_2')
        elif b > PricingCalculator.min_size_tier_3():
            b, p = PricingCalculator.resolve_maxed_tier_2(b, p)
            p += PricingCalculator.bytes_to_price_for_tier(b, 'standard_tier_3')
        else:
            raise Exception()
        return PricingCalculator.float_to_usd(p)

    @staticmethod
    def readable_sizes():
        """ Returns dictionary where the keys are readable size units and the values are their sizes in bytes"""
        return {
            'TB': 1_000_000_000_000.0,
            'GB': 1_000_000_000.0,
            'MB': 1_000_000.0,
            'KB': 1_000.0
        }

    @staticmethod
    def bytes_to_readable(b):
        """ Takes a float of bytes b and returns a readable string of size in TB/GB/MB/KB/Bytes"""
        for size_unit, size_bytes in PricingCalculator.readable_sizes.items():
            if b >= size_bytes:
                return '{} {}'.format(round(b / size_bytes, 2), size_unit)
        return '{} Bytes'.format(round(b, 2))

    @staticmethod
    def validate():
        # Price and Bytes for Tier 1 and Tier 2 when maxed out
        assert PricingCalculator.float_to_usd(PricingCalculator.max_cost_tier_1()) == '$1,177.60',\
            'tier 1 != {}. price error or prices have changed'.format(
                PricingCalculator.float_to_usd(PricingCalculator.float_to_usd(PricingCalculator.max_cost_tier_1())))
        assert PricingCalculator.max_size_tier_1() == 54_975_581_388_800.0,\
            'tier 1 != {}. byte calculation error'.format(PricingCalculator.max_size_tier_1())

        assert PricingCalculator.float_to_usd(PricingCalculator.max_cost_tier_2()) == '$10,137.60',\
            'tier 1 != {}. price error or prices have changed'.format(
                PricingCalculator.float_to_usd(PricingCalculator.float_to_usd(PricingCalculator.max_cost_tier_2())))
        assert PricingCalculator.max_size_tier_2() == 494_780_232_499_200.0,\
            'tier 1 != {}. byte calculation error'.format(PricingCalculator.max_size_tier_2())
