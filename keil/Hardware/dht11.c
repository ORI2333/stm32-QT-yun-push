#include "stm32f10x.h"
#include "DHT11.h"
#include "Delay.h"

// 通用 IO 输出模式
void DHT11_IO_OUT(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    GPIO_InitTypeDef GPIO_InitStructure;
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOx, &GPIO_InitStructure);
}

// 通用 IO 输入模式
void DHT11_IO_IN(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    GPIO_InitTypeDef GPIO_InitStructure;
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOx, &GPIO_InitStructure);
}

// 通用复位信号
void DHT11_RST(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    DHT11_IO_OUT(GPIOx, GPIO_Pin);
    GPIO_ResetBits(GPIOx, GPIO_Pin);
    Delay_ms(20);
    GPIO_SetBits(GPIOx, GPIO_Pin);
    Delay_us(30);
}

// 通用应答检测
u8 DHT11_Check(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    u8 retry=0;
    DHT11_IO_IN(GPIOx, GPIO_Pin);
    while((GPIO_ReadInputDataBit(GPIOx,GPIO_Pin)==1) && retry<100)
    {
        retry++;
        Delay_us(1);
    }
    if(retry>=100) return 1;
    else retry=0;

    while((GPIO_ReadInputDataBit(GPIOx,GPIO_Pin)==0) && retry<100)
    {
        retry++;
        Delay_us(1);
    }
    if(retry>=100) return 1;
    return 0;
}

// 通用初始化
u8 DHT11_Init(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, uint32_t GPIO_RCC)
{
    RCC_APB2PeriphClockCmd(GPIO_RCC, ENABLE);
    DHT11_RST(GPIOx, GPIO_Pin);
    return DHT11_Check(GPIOx, GPIO_Pin);
}

// 读一位（内部用）
u8 DHT11_Read_Bit(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    u8 retry=0;
    while((GPIO_ReadInputDataBit(GPIOx,GPIO_Pin)==1) && retry<100)
    {
        retry++;
        Delay_us(1);
    }
    retry=0;
    while((GPIO_ReadInputDataBit(GPIOx,GPIO_Pin)==0) && retry<100)
    {
        retry++;
        Delay_us(1);
    }
    Delay_us(40);
    if(GPIO_ReadInputDataBit(GPIOx,GPIO_Pin)==1) return 1;
    else return 0;
}

// 读一字节（内部用）
u8 DHT11_Read_Byte(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin)
{
    u8 i,dat;
    dat=0;
    for(i=0;i<8;i++)
    {
        dat<<=1;
        dat |= DHT11_Read_Bit(GPIOx, GPIO_Pin);
    }
    return dat;
}

// 通用读数据（你调用的函数）
u8 DHT11_Read_Data(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, u8 *temp, u8 *humi)
{
    u8 buf[5];
    u8 i;
    DHT11_RST(GPIOx, GPIO_Pin);
    if(DHT11_Check(GPIOx, GPIO_Pin)==0)
    {
        for(i=0;i<5;i++)
        {
            buf[i] = DHT11_Read_Byte(GPIOx, GPIO_Pin);
        }
        if((buf[0]+buf[1]+buf[2]+buf[3]) == buf[4])
        {
            *humi = buf[0];
            *temp = buf[2];
        }
    }
    else return 1;
    return 0;
}

